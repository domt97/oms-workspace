"""Tests for .claude/hooks/guard_git.py — run with: python3 -m unittest discover -s scripts/tests"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude/hooks/guard_git.py"
SETTINGS = ROOT / ".claude/settings.json"

spec = importlib.util.spec_from_file_location("guard_git", HOOK)
guard_git = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard_git)


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                   check=True, capture_output=True)


def make_repo(path: Path, branch: str) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    git(path, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    return path


class GuardGitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ws = Path(cls._tmp.name).resolve() / "ws"
        make_repo(cls.ws, "chore/work")
        stores = make_repo(cls.ws / "repos/stores-service", "feature/x")
        git(stores, "commit", "-q", "--allow-empty", "-m", "init")
        git(stores, "tag", "candidate")                     # a tag whose name does not look like a version
        make_repo(cls.ws / "repos/inventory-service", "develop")
        make_repo(cls.ws / "repos/oms-core", "master")
        cls.outside = Path(cls._tmp.name).resolve() / "outside"  # not inside any git repository
        cls.outside.mkdir()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def decide(self, command: str, cwd: str | None = None) -> str | None:
        return guard_git.decide(command, str(self.ws) if cwd is None else str(self.ws / cwd))

    def assertBlocked(self, command: str, cwd: str | None = None) -> None:
        self.assertIsNotNone(self.decide(command, cwd), f"should be blocked: {command!r}")

    def assertNoOpinion(self, command: str, cwd: str | None = None) -> None:
        self.assertIsNone(self.decide(command, cwd), f"should not be blocked: {command!r}")

    def assertAllBlocked(self, commands: tuple, cwd: str | None = None) -> None:
        for command in commands:
            with self.subTest(command=command):
                self.assertBlocked(command, cwd)

    def assertAllNoOpinion(self, commands: tuple, cwd: str | None = None) -> None:
        for command in commands:
            with self.subTest(command=command):
                self.assertNoOpinion(command, cwd)

    # --- pushes to master / develop, in every spelling -------------------------------------------------

    def test_push_naming_a_protected_branch(self) -> None:
        self.assertAllBlocked((
            "git push origin master",
            "git push origin develop",
            "git push -u origin master",
            "git push origin HEAD:master",
            "git push origin feature/x:develop",
            "git push origin refs/heads/master",
            "git push origin HEAD:refs/heads/develop",
            "git push origin feature/x master",
            "git -C repos/stores-service push origin master",
            "git -c push.default=current -C repos/stores-service push origin develop",
            "cd repos/stores-service && git push origin master",
            "cd repos/stores-service\ngit push origin master",
            "GIT_TRACE=1 git push origin master",
            "env GIT_TRACE=1 git push origin master",
            "command git push origin master",
            "/usr/bin/git push origin master",
            "bash -c 'git push origin master'",
            "bash -lc \"cd repos/stores-service && git push origin develop\"",
            "eval git push origin master",
            "./gradlew test && git -C repos/stores-service push origin HEAD:master",
            "(cd repos/stores-service; git push origin master)",
            "echo done # then\ngit push origin master",
            "git push > push.log origin master",
        ))

    def test_line_continuations_do_not_hide_the_rest_of_the_command(self) -> None:
        self.assertAllBlocked((
            "git push origin \\\n  master",
            "git push \\\n  --force origin feature/x",
            "git -C repos/stores-service push \\\n    origin \\\n    HEAD:develop",
            "gh pr merge 12 \\\n  -R domt97/oms-core",
        ), "repos/stores-service")
        self.assertNoOpinion("git push -u \\\n  origin feature/x", "repos/stores-service")

    def test_shell_keywords_and_wrappers_do_not_hide_the_command(self) -> None:
        self.assertAllBlocked((
            "if true; then git push origin master; fi",
            "if ! git diff --quiet; then echo dirty; else git push origin develop; fi",
            "for r in stores-service inventory-service; do git -C repos/$r push origin develop; done",
            "while true; do git push origin master; done",
            "{ git push --force origin feature/x; }",
            "! git push origin master",
            "time git push origin master",
            "timeout 60 git push origin master",
            "timeout -s KILL 60 git push origin master",
            "nice -n 5 git push origin master",
            "nohup git push origin master",
            "sudo -u someone git push origin master",
        ), "repos/stores-service")

    def test_redirections_are_not_read_as_arguments(self) -> None:
        self.assertBlocked("git push origin 2>&1", "repos/inventory-service")
        self.assertBlocked("git push 2>&1 | tail -5", "repos/inventory-service")
        self.assertBlocked("cd repos/inventory-service && git push origin 2>&1 | tail -5")
        self.assertBlocked("git push origin master 2>/dev/null", "repos/stores-service")
        self.assertAllNoOpinion((
            "git push -u origin feature/x 2>&1 | tail -5",
            "git push origin 2>&1",
            "git push origin feature/x > /tmp/master",
            "git push origin feature/x &> develop",
            "git tag 2>/dev/null",
            "git tag -l 2>&1 | head",
        ), "repos/stores-service")

    def test_push_without_a_branch_name_uses_the_current_branch(self) -> None:
        self.assertBlocked("git push", "repos/inventory-service")
        self.assertBlocked("git push origin", "repos/oms-core")
        self.assertBlocked("git push -u origin HEAD", "repos/inventory-service")
        self.assertBlocked("git -C repos/inventory-service push")
        self.assertBlocked("cd repos/oms-core && git push")
        self.assertBlocked('git push origin "$(git branch --show-current)"', "repos/inventory-service")
        self.assertBlocked("git push origin $(git branch --show-current)", "repos/inventory-service")
        self.assertBlocked("git push origin `git rev-parse --abbrev-ref HEAD`", "repos/inventory-service")
        self.assertNoOpinion("git push", "repos/stores-service")
        self.assertNoOpinion("git push -u origin HEAD", "repos/stores-service")
        self.assertNoOpinion('git push -u origin "$(git branch --show-current)"', "repos/stores-service")
        self.assertNoOpinion("git push -u origin $(git rev-parse --abbrev-ref HEAD)", "repos/stores-service")
        self.assertNoOpinion("git -C repos/stores-service push")
        self.assertNoOpinion("cd repos/stores-service && git push")
        self.assertNoOpinion("git push")  # the workspace itself is on chore/work
        self.assertNoOpinion("git push", "repos")  # a plain sub-directory of the workspace repo

    def test_a_checkout_earlier_in_the_line_makes_the_current_branch_unknown(self) -> None:
        self.assertAllBlocked((
            "git checkout develop && git merge feature/x && git push",
            "git checkout develop && git pull && git push origin HEAD",
            'git switch develop && git push -u origin "$(git branch --show-current)"',
            "git checkout develop; bash -c 'git push'",
            "git checkout -b fix/y && git push -u origin HEAD",
        ), "repos/stores-service")
        self.assertBlocked("git -C repos/stores-service checkout master && git -C repos/stores-service push")
        self.assertAllNoOpinion((
            "git checkout -b fix/y && git push -u origin fix/y",
            "git checkout develop && git pull --ff-only origin develop",
            "git checkout -- README.md && git push",
            "git switch -c fix/z origin/develop",
        ), "repos/stores-service")

    def test_a_command_after_a_here_document_is_still_checked(self) -> None:
        self.assertAllBlocked((
            "cat <<'EOF' > f\nx\nEOF\ngit push origin master",
            "git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\" && git push origin master",
            "cat <<EOF && git push origin master\nx\nEOF",
            "cat <<- EOF\n\tx\n\n\tEOF\ngit push origin master",
        ), "repos/stores-service")
        self.assertNoOpinion("wc -l <<<foo && git status", "repos/stores-service")

    def test_push_is_refused_when_the_branch_is_unknown(self) -> None:
        self.assertIsNotNone(guard_git.decide("git push", str(self.outside)))
        self.assertIsNotNone(guard_git.decide("git push -u origin HEAD", str(self.outside)))
        self.assertIsNone(guard_git.decide("git push -u origin feature/x", str(self.outside)))
        self.assertBlocked("git -C repos/missing push")
        self.assertBlocked("cd \"$SOMEWHERE\" && git push")
        self.assertBlocked("cd repos/stores-service && cd - && git push")

    def test_a_variable_as_the_branch_is_refused(self) -> None:
        self.assertAllBlocked((
            'B=develop; git push origin "$B"',
            "git push origin $BRANCH",
            "git push origin HEAD:$TARGET",
            "git push origin $(cat branch.txt)",
        ), "repos/stores-service")

    def test_cd_inside_a_subshell_does_not_leak(self) -> None:
        self.assertNoOpinion("(cd repos/inventory-service && git status); git push")
        self.assertBlocked("(cd repos/stores-service && git status); git push", "repos/inventory-service")
        self.assertBlocked("echo $(cd repos/stores-service && git status); git push", "repos/inventory-service")
        self.assertBlocked("pushd repos/stores-service && popd && git push")  # after popd the directory is unknown

    def test_force_delete_mirror_all_and_wildcard_pushes(self) -> None:
        self.assertAllBlocked((
            "git push --force origin feature/x",
            "git push -f origin feature/x",
            "git push origin feature/x --force",
            "git push origin feature/x -f",
            "git push -uf origin feature/x",
            "git push --force-with-lease origin feature/x",
            "git push --force-with-lease=feature/x origin feature/x",
            "git push origin +feature/x",
            "git -C repos/stores-service push --force-with-lease",
            "git push --mirror",
            "git push --all origin",
            "git push --prune origin",
            "git push origin 'refs/heads/*:refs/heads/*'",
            "git push origin --delete feature/x",
            "git push origin :feature/x",
            "git push -d origin feature/x",
        ), "repos/stores-service")

    def test_tag_pushes(self) -> None:
        self.assertAllBlocked((
            "git push --tags",
            "git push --follow-tags origin feature/x",
            "git push origin refs/tags/v1.2.0-rc.1",
            "git push origin tag v1.2.0-rc.1",
            "git push origin v1.4.0-rc.1",              # looks like a version
            "git push origin v1.4.0",
            "git push origin candidate",                # an existing tag of this repo
            "git push origin candidate:candidate",
        ), "repos/stores-service")
        self.assertBlocked("git -C repos/stores-service push origin candidate")
        self.assertNoOpinion("git push origin candidate", "repos/inventory-service")  # no such tag there: a branch name
        self.assertNoOpinion("git push -u origin v2-migration", "repos/stores-service")

    def test_a_push_of_the_working_branch_is_left_to_the_ask_rule(self) -> None:
        self.assertAllNoOpinion((
            "git push -u origin feature/x",
            "git push origin feature/x",
            "git push origin HEAD:feature/x",
            "git push origin HEAD:refs/heads/feature/x",
            "git -C repos/stores-service push -u origin fix/master-data",
            "git -c push.negotiate=true push -u origin docs/develop-notes",
            "git push -o ci.skip origin feature/x",
            "git push --push-option ci.skip origin feature/x",
            "git push --repo origin",
            "timeout 120 git push -u origin feature/x",
            "if git diff --quiet; then git push -u origin feature/x; fi",
        ), "repos/stores-service")

    # --- other hard rules -------------------------------------------------------------------------

    def test_reset_hard(self) -> None:
        self.assertBlocked("git reset --hard")
        self.assertBlocked("git reset --hard origin/develop")
        self.assertBlocked("git -C repos/stores-service reset --hard HEAD~1")
        self.assertNoOpinion("git reset HEAD~1")
        self.assertNoOpinion("git reset --soft HEAD~1")

    def test_branches_are_not_deleted(self) -> None:
        self.assertAllBlocked((
            "git branch -D feature/x",
            "git branch -d feature/x",
            "git branch --delete feature/x",
            "git branch -d -f feature/x",
            "git branch -df feature/x",
            "git branch --delete --force feature/x",
            "git branch --color -D feature/x",
            "git -C repos/stores-service branch -D feature/x",
            "cd repos/stores-service && git branch -d feature/x",
        ))
        self.assertAllNoOpinion((
            "git branch",
            "git branch -a",
            "git branch -vv",
            "git branch -r",
            "git branch --show-current",
            "git branch -m old-name new-name",
            "git branch --sort=-committerdate",
            "git branch --sort -committerdate",
            "git branch -r --contains develop",
            "git -C repos/stores-service branch --show-current",
        ))

    def test_tags_and_releases_are_the_users(self) -> None:
        self.assertAllBlocked((
            "git tag v1.2.0-rc.1",
            "git tag -a v1.2.0 -m 'release'",
            "git -C repos/oms-core tag v1.2.0-rc.1",
            "git tag -d v1.2.0-rc.1",
            "gh release create v1.2.0 --generate-notes",
            "gh release delete v1.2.0",
            "gh release upload v1.2.0 build/libs/x.jar",
        ))
        self.assertAllNoOpinion((
            "git tag",
            "git tag -l 'v1.*'",
            "git tag --list",
            "git tag --contains HEAD",
            "git tag --sort=-creatordate",
            "gh release list",
            "gh release view v1.2.0",
        ))

    def test_oms_core_pull_requests_are_merged_by_the_user(self) -> None:
        self.assertBlocked("gh pr merge 12 --squash", "repos/oms-core")
        self.assertBlocked("gh pr merge 12 -R domt97/oms-core")
        self.assertBlocked("gh -R domt97/oms-core pr merge 12")
        self.assertBlocked("gh pr merge https://github.com/domt97/oms-core/pull/12")
        self.assertBlocked("cd repos/oms-core && gh pr merge 12")
        self.assertNoOpinion("gh pr merge 12", "repos/stores-service")
        self.assertNoOpinion("gh pr merge 61 -R domt97/oms-workspace")
        self.assertNoOpinion("gh pr create --base master --title x --body y", "repos/oms-core")
        self.assertNoOpinion("gh pr view 12 -R domt97/oms-core")

    def test_gh_api_cannot_do_what_the_commands_may_not(self) -> None:
        self.assertAllBlocked((
            "gh api -X PUT repos/domt97/oms-core/pulls/12/merge",
            "gh api --method PUT repos/domt97/oms-core/pulls/12/merge -f merge_method=squash",
            "gh api repos/domt97/oms-core/releases -f tag_name=v1.2.0",
            "gh api -X DELETE repos/domt97/oms-core/releases/123",
            "gh api repos/domt97/oms-core/git/refs -f ref=refs/tags/v1.2.0-rc.1 -f sha=abc123",
            "gh api -XDELETE repos/domt97/stores-service/git/refs/heads/develop",
            "gh api --method=PATCH repos/domt97/stores-service/git/refs/heads/master -f sha=abc123 -F force=true",
            "gh api -X DELETE repos/domt97/stores-service/git/refs/heads/feature/x",
            "gh api repos/domt97/oms-core/releases -ftag_name=v1.2.0",
        ))
        self.assertAllNoOpinion((
            "gh api repos/domt97/oms-core/pulls/12/merge",                     # GET: is it merged?
            "gh api repos/domt97/oms-core/releases",
            "gh api 'repos/domt97/stores-service/actions/runs?branch=feature/x'",
            "gh api repos/domt97/oms-workspace/pulls -f title=x -f head=chore/x -f base=master",
            "gh api -X PUT repos/domt97/stores-service/pulls/12/merge",       # left to the ask rule
            "gh api repos/domt97/stores-service/git/refs/heads/develop",
        ))

    # --- things that only look dangerous ----------------------------------------------------------------

    def test_text_that_is_not_a_command_is_ignored(self) -> None:
        self.assertAllNoOpinion((
            "git commit -m 'never run git push origin master here'",
            "git commit -m \"docs: explain why git push --force is blocked\"",
            "echo 'git push origin master'",
            "grep -rn 'git push origin master' .claude",
            "git log --oneline master",
            "git diff master...HEAD",
            "git checkout develop && git pull --ff-only origin develop",
            "git checkout -b feature/y",
            "git switch -c fix/z origin/develop",
            "git fetch origin master:master",
            "git merge --ff-only origin/develop",
            "git status --porcelain          # must be empty",
            "cat > notes.md <<'EOF'\ngit push origin master\ngit reset --hard\nEOF",
            "git commit -m \"$(cat <<'EOF'\nfix: guard\n\ngit push origin master is blocked\nEOF\n)\"",
            "git commit -m \"$(cat <<'EOF'\nfix: don't (ever) push :)\n\n\"git push origin master\" stays blocked\nEOF\n)\"",
            "cat <<EOF > notes.md\nit's fine (really\ngit push origin master\nEOF\ngit status",
            "# don't push yet\ngit status\n# it's fine",
            "./scripts/sync-repos.sh",
            "ls -la && pwd",
            "",
        ), "repos/stores-service")

    def test_comments_are_read_like_the_shell_reads_them(self) -> None:
        # a comment ends at the end of its line, whatever it contains
        self.assertBlocked("# don't forget\ngit push origin master\n# it's done", "repos/stores-service")
        self.assertBlocked("# note \\\ngit push origin master", "repos/stores-service")
        self.assertBlocked("git status # check \\\ngit push", "repos/inventory-service")
        self.assertBlocked("git tag v1.0.0 # it's time")
        self.assertBlocked("git branch -D feature/x # it's merged")
        # a quoted word that starts with # is an argument, not a comment
        self.assertBlocked('cd repos/inventory-service && git commit -m "#28 tune expiry" && git push')
        self.assertBlocked('echo "# done" && git -C repos/stores-service push --force-with-lease origin fix/x')
        self.assertAllNoOpinion((
            'git commit -m "#12 fix"',
            "git status # note",
            "git status # don't mind me",
            "git push -u origin feature/x # don't worry",
            "git status --porcelain          # must be empty — otherwise stop",
        ), "repos/stores-service")

    def test_quoted_punctuation_and_empty_arguments_are_words(self) -> None:
        self.assertAllBlocked((
            'gh pr merge 12 --squash --body "" -R domt97/oms-core',
            'gh pr merge 12 --subject ">" -R domt97/oms-core',
            'gh pr merge 12 --subject ";" -R domt97/oms-core',
            'git tag -a -m "" v1.2.0-rc.1',
            'git -C "" push origin master',
            'git push -o "" origin master',
            "git push origin '' master",
            "bash -c 'cd repos/stores-service && git push origin master'",
            'echo "<<EOF"\ngit push origin master',
        ))
        self.assertAllNoOpinion((
            'git commit --allow-empty-message -m ""',
            'git commit -m "a; b && c | d > e (f)"',
            "git log --format='%h %s' -n 5",
        ), "repos/stores-service")

    def test_command_substitutions_are_checked_as_commands(self) -> None:
        self.assertAllBlocked((
            'echo "$(git push origin master)"',
            "echo `git push origin master`",
            "OUT=$(git -C repos/stores-service push --force origin feature/x)",
            'echo "$(cd repos/inventory-service && git push)"',
        ))
        self.assertNoOpinion('echo "on $(git branch --show-current), $(git rev-parse --short HEAD)"')

    def test_a_substituted_branch_must_be_read_where_the_push_runs(self) -> None:
        self.assertBlocked("cd repos/inventory-service; git -C ../stores-service push origin $(git branch --show-current)")
        self.assertBlocked('git -C repos/stores-service push origin "$(git branch --show-current)"')
        self.assertNoOpinion('cd repos/stores-service && git push -u origin "$(git branch --show-current)"')

    def test_the_environment_can_point_git_and_gh_elsewhere(self) -> None:
        self.assertBlocked("GH_REPO=domt97/oms-core gh pr merge 12")
        self.assertBlocked("env GH_REPO=domt97/oms-core gh pr merge 12 --squash")
        self.assertBlocked("GIT_DIR=repos/inventory-service/.git git push", "repos/stores-service")
        self.assertBlocked("git --git-dir=repos/inventory-service/.git push", "repos/stores-service")
        self.assertNoOpinion("GH_REPO=domt97/stores-service gh pr merge 12")
        self.assertNoOpinion("GIT_DIR=.git git push -u origin feature/x", "repos/stores-service")

    def test_xargs_is_followed(self) -> None:
        self.assertBlocked("echo origin | xargs git push --force")
        self.assertBlocked("echo master | xargs -n 1 git push origin master")

    def test_unparseable_commands_fail_closed_for_guarded_commands(self) -> None:
        self.assertAllBlocked((
            "echo \"unbalanced && git push origin master",
            "echo 'oops && git -C repos/x push --force origin feature/x",
            "echo 'oops && git reset --hard",
            "echo \"oops && git \\\n  push origin master",
            "echo 'oops && git tag v1.0.0",
            "echo 'oops && gh pr merge 12",
        ))
        self.assertNoOpinion("echo \"unbalanced && git status")

    # --- the hook contract and its configuration --------------------------------------------------------------

    def run_hook(self, payload: object) -> subprocess.CompletedProcess:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(HOOK)], input=text, capture_output=True, text=True, timeout=30)

    def test_exit_codes(self) -> None:
        blocked = self.run_hook({"tool_name": "Bash", "cwd": str(self.ws),
                                 "tool_input": {"command": "git -C repos/stores-service push origin master"}})
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("a push to master", blocked.stderr)

        allowed = self.run_hook({"tool_name": "Bash", "cwd": str(self.ws), "tool_input": {"command": "git status"}})
        self.assertEqual((allowed.returncode, allowed.stderr), (0, ""))

        other_tool = self.run_hook({"tool_name": "Read", "tool_input": {"file_path": "x"}})
        self.assertEqual(other_tool.returncode, 0)

    def test_the_guard_fails_closed(self) -> None:
        unreadable = self.run_hook("not json")
        self.assertEqual(unreadable.returncode, 2)
        self.assertIn("the guard itself failed", unreadable.stderr)

        crash = self.run_hook({"tool_name": "Bash", "cwd": str(self.ws), "tool_input": {"command": 123}})
        self.assertEqual(crash.returncode, 2)
        self.assertIn("the guard itself failed", crash.stderr)

    def test_settings_register_the_hook_and_mirror_every_git_rule(self) -> None:
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))

        handlers = [h for group in settings["hooks"]["PreToolUse"] if group.get("matcher") == "Bash" for h in group["hooks"]]
        commands = [h["command"] for h in handlers if h.get("type") == "command"]
        self.assertTrue(any(".claude/hooks/guard_git.py" in c for c in commands), commands)
        self.assertTrue(HOOK.is_file())

        for kind in ("ask", "deny"):
            rules = settings["permissions"][kind]
            for rule in rules:
                if rule.startswith("Bash(git ") and not rule.startswith("Bash(git * "):
                    mirror = "Bash(git * " + rule[len("Bash(git "):]
                    with self.subTest(kind=kind, rule=rule):
                        self.assertIn(mirror, rules)


if __name__ == "__main__":
    unittest.main()
