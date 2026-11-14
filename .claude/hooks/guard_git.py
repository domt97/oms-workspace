#!/usr/bin/env python3
"""PreToolUse hook for the Bash tool: refuse the git/gh commands CLAUDE.md forbids, in the spellings people use.

The `ask`/`deny` rules in .claude/settings.json match a command by its text, so `git -C repos/x push origin master`
or `cd repos/x && git push` (on `develop`) are not caught by `Bash(git push * master)`. This hook parses the command
instead and blocks:

- a push to `master` or `develop` (named in a refspec, or the current branch when no refspec is given), and a
  push of "the current branch" after a `git checkout`/`git switch` in the same command line;
- a force push, `--mirror`, `--all`, `--prune`, a wildcard refspec, deleting a remote branch, pushing a tag;
- `git reset --hard`, deleting a local branch (`git branch -d|-D|--delete`);
- creating or deleting a tag, `gh release create|delete|edit|upload` (only the user tags and releases);
- `gh pr merge` on oms-core (only the user merges oms-core PRs);
- `gh api` calls that merge an oms-core PR, write a tag or a release, write `master`/`develop`, or delete a branch.

Everything else gets no opinion: the settings.json rules still ask before a commit, push, merge or PR.

Limits. This reads the command line only. It does not see inside a script the command runs, a here-document fed
to a shell (`bash <<EOF`), `find -exec`, a git alias, or a variable it cannot resolve (a variable used as the branch
of a push is refused; any other use is not followed). Other writes through `gh api` (the merges and contents
endpoints, GraphQL) are left to the `ask` rule. It is a guard against a wrong command, not a sandbox, and the rules
in CLAUDE.md hold whether or not something blocks.

Contract (Claude Code hooks): JSON on stdin, exit 0 = no opinion, exit 2 = blocked and stderr is shown to Claude.
The guard fails closed on its own errors: unreadable input or an internal error also exits 2. What it cannot catch
is not running at all (no `python3`) or being stopped by the hook timeout; the `ask`/`deny` rules still apply then.
Only the Python standard library is used. Tests: python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

PROTECTED = ("master", "develop")
OPERATOR_CHARS = "();<>|&"
GIT_OPTIONS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env")
PUSH_OPTIONS_WITH_VALUE = ("--repo", "--push-option", "--receive-pack", "--exec")
BRANCH_OPTIONS_WITH_VALUE = ("--sort", "--format", "--points-at", "--contains", "--no-contains", "--merged", "--no-merged")
KEYWORDS = ("if", "then", "else", "elif", "do", "while", "until", "{", "!", "time")
WRAPPERS = {  # program -> its options that take a value
    "command": (), "builtin": (), "exec": (), "nohup": (),
    "sudo": ("-u", "-g"), "env": ("-u", "--unset", "-C", "--chdir"),
    "nice": ("-n", "--adjustment"), "timeout": ("-s", "--signal", "-k", "--kill-after"),
    "xargs": ("-I", "-n", "-P", "-L", "-d", "-s", "-E", "-a"),
}
SHELLS = ("bash", "sh", "zsh", "dash")
TAG_READ_ONLY = ("-l", "--list", "-v", "--verify", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at")
ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
VERSION_TAG_RE = re.compile(r"^v\d+\.\d+")
CURRENT_BRANCH_RE = re.compile(
    r"git\s+(?:branch\s+--show-current|rev-parse\s+--abbrev-ref\s+HEAD|symbolic-ref\s+(?:-q\s+)?--short\s+(?:-q\s+)?HEAD)")
CURRENT = "\x00current-branch\x00"   # stands for "$(git branch --show-current)" inside a word

HOW_TO = "Push only the working branch and open a PR; if this is really needed, ask the user to run it."
NAME_IT = "name the branch: git push -u origin <branch>"
MOVED = "a push of the current branch after a checkout or switch in the same command line; " + NAME_IT

# Used only when the command cannot be tokenised (unbalanced quotes): refuse anything that mentions a guarded command.
_SEG = r"[^\n;&|]*"
FALLBACK_RE = re.compile(
    r"\bgit\b" + _SEG + r"\b(?:push|tag)\b"
    r"|\bgit\b" + _SEG + r"\breset\b" + _SEG + r"--hard"
    r"|\bgit\b" + _SEG + r"\bbranch\b" + _SEG + r"\s(?:-[a-zA-Z]*[dD]|--delete)"
    r"|\bgh\b" + _SEG + r"\b(?:release|api|pr\s+merge)\b")


# --- reading the command line ------------------------------------------------------------------------------

def skip_heredoc_body(text: str, pos: int, delimiters: list[str]) -> int:
    """`pos` is just after the newline that ends a line with here-documents; return the index after their bodies."""
    for delimiter in delimiters:
        while pos < len(text):
            end = text.find("\n", pos)
            line = text[pos:] if end < 0 else text[pos:end]
            pos = len(text) if end < 0 else end + 1
            if line.strip() == delimiter:
                break
    return pos


def read_substitution(text: str, i: int) -> tuple[str, int]:
    """`text[i]` is the first character after `$(`. Return (body, index after the closing parenthesis)."""
    depth, j, quote, pending = 1, i, None, []
    while j < len(text):
        c = text[j]
        if quote == "'":
            quote = None if c == "'" else quote
        elif quote == '"':
            if c == "\\":
                j += 1
            elif c == '"':
                quote = None
        elif c == "\\":
            j += 1
        elif c in "'\"":
            quote = c
        elif c == "<" and HEREDOC_RE.match(text, j):
            m = HEREDOC_RE.match(text, j)
            pending.append(m.group(2))
            j = m.end() - 1
        elif c == "\n" and pending:
            j = skip_heredoc_body(text, j + 1, pending) - 1
            pending = []
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[i:j], j + 1
        j += 1
    raise ValueError("unterminated $(")


def read_backticks(text: str, i: int) -> tuple[str, int]:
    j = i
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == "`":
            return text[i:j], j + 1
        j += 1
    raise ValueError("unterminated backtick")


def split_commands(text: str) -> list:
    """A small shell reader. Returns the simple commands in order, as {"words": [...], "nested": [...]}, and the
    markers "(" and ")" for subshells.

    - Quotes are honoured: a quoted `;`, `#`, `>` or an empty `""` is a word, never an operator or a comment.
    - A comment runs to the end of its physical line; a backslash-newline joins lines everywhere else.
    - Redirections are dropped (`2>&1`, `> file`), and here-document bodies are skipped: they are data.
    - `$(…)` and backticks stay part of their word; their bodies are returned in "nested" to be checked as commands.
      `$(git branch --show-current)` and its equivalents become the CURRENT marker.

    Raises ValueError on unbalanced quotes.
    """
    items: list = []
    words: list[str] = []
    nested: list[str] = []
    word: list[str] | None = None
    heredocs: list[str] = []
    skip_word = await_delimiter = False
    i, n = 0, len(text)

    def end_word() -> None:
        nonlocal word, skip_word, await_delimiter
        if word is None:
            return
        value, word = "".join(word), None
        if await_delimiter:
            if value.strip("-"):
                heredocs.append(value.lstrip("-").strip())
                await_delimiter = skip_word = False
        elif skip_word:
            skip_word = False
        else:
            words.append(value)

    def flush() -> None:
        nonlocal words, nested, skip_word, await_delimiter
        end_word()
        if words or nested:
            items.append({"words": words, "nested": nested})
        words, nested = [], []
        skip_word = await_delimiter = False

    def substitution(body: str) -> None:
        if CURRENT_BRANCH_RE.fullmatch(body.strip()):
            word.append(CURRENT)
        else:
            word.append("$(" + body + ")")
            nested.append(body)

    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
                continue
            word = word if word is not None else []
            if i + 1 < n:
                word.append(text[i + 1])
            i += 2
        elif c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ValueError("unterminated '")
            word = word if word is not None else []
            word.append(text[i + 1:j])
            i = j + 1
        elif c == '"':
            word = word if word is not None else []
            i += 1
            while True:
                if i >= n:
                    raise ValueError('unterminated "')
                d = text[i]
                if d == '"':
                    i += 1
                    break
                if d == "\\" and i + 1 < n:
                    if text[i + 1] != "\n":
                        word.append(text[i + 1] if text[i + 1] in '"\\$`' else d + text[i + 1])
                    i += 2
                elif d == "$" and i + 1 < n and text[i + 1] == "(":
                    body, i = read_substitution(text, i + 2)
                    substitution(body)
                elif d == "`":
                    body, i = read_backticks(text, i + 1)
                    substitution(body)
                else:
                    word.append(d)
                    i += 1
        elif c == "$" and i + 1 < n and text[i + 1] == "(":
            word = word if word is not None else []
            body, i = read_substitution(text, i + 2)
            substitution(body)
        elif c == "`":
            word = word if word is not None else []
            body, i = read_backticks(text, i + 1)
            substitution(body)
        elif c == "#" and word is None:
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif c in " \t\r":
            end_word()
            i += 1
        elif c == "\n":
            flush()
            pending, heredocs = heredocs, []
            i = skip_heredoc_body(text, i + 1, pending) if pending else i + 1
        elif c in OPERATOR_CHARS:
            j = i
            while j < n and text[j] in OPERATOR_CHARS:
                j += 1
            run = text[i:j]
            if any(ch in ";()" for ch in run) or not any(ch in "<>" for ch in run):
                flush()
                items.extend(ch for ch in run if ch in "()")
            else:                                    # a redirection: drop the fd glued to it and the target after it
                if word is not None and "".join(word).isdigit():
                    word = None
                else:
                    end_word()
                skip_word = True
                await_delimiter = "<<" in run and "<<<" not in run
            i = j
        else:
            word = word if word is not None else []
            word.append(c)
            i += 1
    flush()
    return items


# --- the rules --------------------------------------------------------------------------------------------------

class State:
    """Where the next simple command runs: follows `cd` through a compound command, and remembers whether a
    `git checkout`/`git switch` came earlier — the branch read now is then not the branch at push time."""

    def __init__(self, cwd: str | None, branch_moved: bool = False) -> None:
        self.cwd = cwd
        self.branch_moved = branch_moved

    def resolve(self, path: str) -> str | None:
        if "$" in path or "`" in path or CURRENT in path:
            return None
        path = os.path.expanduser(path)
        if os.path.isabs(path):
            return os.path.normpath(path)
        if self.cwd is None:
            return None
        return os.path.normpath(os.path.join(self.cwd, path))


def git_out(repo_dir: str | None, *args: str) -> subprocess.CompletedProcess | None:
    if repo_dir is None or not os.path.isdir(repo_dir):
        return None
    try:
        return subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None


def current_branch(repo_dir: str | None) -> str | None:
    out = git_out(repo_dir, "symbolic-ref", "--short", "-q", "HEAD")
    return (out.stdout.strip() or None) if out else None


def is_variable(text: str) -> bool:
    return "$" in text or "`" in text or CURRENT in text


def is_tag(name: str, repo_dir: str | None) -> bool:
    if not name or is_variable(name):
        return False
    if VERSION_TAG_RE.match(name):
        return True
    out = git_out(repo_dir, "show-ref", "--verify", "-q", "refs/tags/" + name)
    return out is not None and out.returncode == 0


def check_push(args: list[str], repo_dir: str | None, shell_dir: str | None, branch_moved: bool = False) -> str | None:
    positional, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            positional += args[i + 1:]
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in ("--force", "--mirror") or name.startswith("--force-with-lease"):
                return "a force push (%s)" % name
            if name in ("--all", "--branches"):
                return "a push of every branch (%s), which includes master and develop" % name
            if name in ("--tags", "--follow-tags"):
                return "a push of tags (%s); only the user tags and releases" % name
            if name in ("--delete", "--prune"):
                return "deleting remote branches or tags (%s)" % name
            if name in PUSH_OPTIONS_WITH_VALUE and "=" not in a:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            flags = a[1:]
            if "f" in flags:
                return "a force push (%s)" % a
            if "d" in flags:
                return "deleting a remote branch or tag"
            if flags.endswith("o"):
                i += 1
        else:
            positional.append(a)
        i += 1

    refspecs = positional[1:]
    if not refspecs:
        if branch_moved:
            return MOVED
        branch = current_branch(repo_dir)
        if branch is None:
            return "a push without a branch name where the current branch cannot be read; " + NAME_IT
        if branch in PROTECTED:
            return "a push while on %s" % branch
        return None

    for ref in refspecs:
        if ref == "tag" or "refs/tags/" in ref:
            return "a push of a tag; only the user tags and releases"
        if ref.startswith("+"):
            return "a force push"
        if "*" in ref:
            return "a push with a wildcard refspec, which can include master and develop"
        src, colon, dst = ref.partition(":")
        if colon and not src:
            return "deleting a remote branch"
        target = dst if colon else src
        if target.startswith("refs/heads/"):
            target = target[len("refs/heads/"):]
        if target == CURRENT:
            # the shell evaluates the substitution in its own directory, which must be the repository pushed from
            if repo_dir is None or shell_dir is None or os.path.normpath(repo_dir) != os.path.normpath(shell_dir):
                return "a push whose branch is read in another directory than the one pushed from; " + NAME_IT
            target = "HEAD"
        if target in ("HEAD", "@"):
            if branch_moved:
                return MOVED
            target = current_branch(repo_dir)
            if target is None:
                return "a push of the current branch where that branch cannot be read; " + NAME_IT
        elif is_variable(target):
            return "a push whose branch is a variable; " + NAME_IT
        if target in PROTECTED:
            return "a push to %s" % target
        if is_tag(src, repo_dir) or is_tag(target, repo_dir):
            return "a push of a tag (%s); only the user tags and releases" % target
    return None


def check_branch(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--delete" or re.fullmatch(r"-[A-Za-z]*[dD][A-Za-z]*", a):
            return "deleting a branch"
        i += 2 if a in BRANCH_OPTIONS_WITH_VALUE else 1
    return None


def check_tag(args: list[str]) -> str | None:
    if any(a in ("-d", "--delete") for a in args):
        return "deleting a tag; only the user tags and releases"
    read_only = any(a in TAG_READ_ONLY or a.startswith(("-n", "--sort", "--format", "--column")) for a in args)
    if not read_only and any(not a.startswith("-") for a in args):
        return "creating a tag; only the user tags and releases"
    return None


def check_git(tokens: list[str], state: State, env: dict) -> str | None:
    i, repo_dir = 1, state.cwd
    if "GIT_DIR" in env or "GIT_WORK_TREE" in env:
        repo_dir = None
    while i < len(tokens) and tokens[i].startswith("-"):
        option = tokens[i].split("=", 1)[0]
        if option in ("--git-dir", "--work-tree"):
            repo_dir = None
        if tokens[i] in GIT_OPTIONS_WITH_VALUE:
            if tokens[i] == "-C" and i + 1 < len(tokens):
                repo_dir = State(repo_dir).resolve(tokens[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(tokens):
        return None
    sub, args = tokens[i], tokens[i + 1:]
    if sub in ("checkout", "switch") and args[:1] != ["--"]:
        state.branch_moved = True
        return None
    if sub == "push":
        return check_push(args, repo_dir, state.cwd, state.branch_moved)
    if sub == "reset" and "--hard" in args:
        return "git reset --hard"
    if sub == "branch":
        return check_branch(args)
    if sub == "tag":
        return check_tag(args)
    return None


def check_gh_api(args: list[str]) -> str | None:
    method, has_fields = None, False
    for j, a in enumerate(args):
        if a in ("-X", "--method") and j + 1 < len(args):
            method = args[j + 1].upper()
        elif a.startswith("--method="):
            method = a.split("=", 1)[1].upper()
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:].upper()
        elif a in ("--field", "--raw-field", "--input") or a.startswith(("--field=", "--raw-field=", "--input=", "-f", "-F")):
            has_fields = True
    if method in ("GET", "HEAD") or (method is None and not has_fields):
        return None
    call = " ".join(args)
    if re.search(r"oms-core/pulls/\d+/merge", call):
        return "merging an oms-core PR through the API; only the user merges there"
    if re.search(r"/releases(?:/|\b)", call):
        return "writing a release through the API; only the user tags and releases"
    if "/git/tags" in call or "refs/tags" in call:
        return "writing a tag through the API; only the user tags and releases"
    if re.search(r"/git/refs/heads/(?:master|develop)\b", call):
        return "writing master or develop through the API"
    if method == "DELETE" and "/git/refs/heads/" in call:
        return "deleting a remote branch through the API"
    return None


def check_gh(tokens: list[str], state: State, env: dict) -> str | None:
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 1 if "=" in tokens[i] else 2
    group = tokens[i] if i < len(tokens) else ""
    action = tokens[i + 1] if i + 1 < len(tokens) else ""
    if group == "release" and action in ("create", "delete", "edit", "upload", "delete-asset"):
        return "gh release %s; only the user tags and releases" % action
    if group == "pr" and action == "merge":
        in_core = state.cwd is not None and "oms-core" in state.cwd.replace("\\", "/").split("/")
        if in_core or "oms-core" in env.get("GH_REPO", "") or any("oms-core" in t for t in tokens):
            return "merging an oms-core PR; a merge can publish a version, so only the user merges there"
    if group == "api":
        return check_gh_api(tokens[i + 1:])
    return None


def strip_prefixes(tokens: list[str]) -> tuple[list[str], dict]:
    """Drop what can stand before the program: assignments (returned), shell keywords, `env`, `timeout 60`, `sudo` …"""
    env: dict = {}
    while tokens:
        head = os.path.basename(tokens[0])
        assignment = ASSIGNMENT_RE.match(tokens[0])
        if assignment:
            env[assignment.group(1)] = assignment.group(2)
            tokens = tokens[1:]
        elif tokens[0] in KEYWORDS:
            tokens = tokens[1:]
        elif head in WRAPPERS:
            tokens = tokens[1:]
            while tokens and (tokens[0].startswith("-") or (head == "env" and ASSIGNMENT_RE.match(tokens[0]))):
                assignment = ASSIGNMENT_RE.match(tokens[0]) if head == "env" else None
                if assignment:
                    env[assignment.group(1)] = assignment.group(2)
                tokens = tokens[2:] if tokens[0] in WRAPPERS[head] else tokens[1:]
            if head == "timeout":
                tokens = tokens[1:]                 # the duration
        else:
            break
    return tokens, env


def check_tokens(tokens: list[str], state: State, depth: int) -> str | None:
    tokens, env = strip_prefixes(tokens)
    if not tokens:
        return None
    program = os.path.basename(tokens[0])

    if program in ("cd", "pushd"):
        target = tokens[1] if len(tokens) > 1 else ""
        state.cwd = state.resolve(target) if target and target != "-" else None
        return None
    if program == "popd":
        state.cwd = None
        return None
    if program in SHELLS and depth < 3:
        for i, token in enumerate(tokens[1:], start=1):
            if token.startswith("-") and not token.startswith("--") and "c" in token and i + 1 < len(tokens):
                return decide(tokens[i + 1], state.cwd, depth + 1, state.branch_moved)
        return None
    if program == "eval" and depth < 3:
        return decide(" ".join(tokens[1:]), state.cwd, depth + 1, state.branch_moved)
    if program == "git":
        return check_git(tokens, state, env)
    if program == "gh":
        return check_gh(tokens, state, env)
    return None


def decide(command: str, cwd: str | None, depth: int = 0, branch_moved: bool = False) -> str | None:
    """Return why the command is refused, or None when this hook has no opinion."""
    try:
        items = split_commands(command)
    except ValueError:
        if FALLBACK_RE.search(command.replace("\\\n", "")):
            return "a guarded git/gh command inside a command line that could not be parsed; simplify the quoting"
        return None
    state, saved = State(cwd, branch_moved), []
    for item in items:
        if item == "(":
            saved.append(state.cwd)
        elif item == ")":
            if saved:
                state.cwd = saved.pop()
        else:
            if depth < 3:
                for body in item["nested"]:
                    reason = decide(body, state.cwd, depth + 1, state.branch_moved)
                    if reason:
                        return reason
            reason = check_tokens(item["words"], state, depth)
            if reason:
                return reason
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if event.get("tool_name") != "Bash":
            return 0
        command = (event.get("tool_input") or {}).get("command") or ""
        reason = decide(command, event.get("cwd") or os.getcwd())
    except Exception as error:  # fail closed: a broken guard must not wave a command through
        print("Blocked by .claude/hooks/guard_git.py: the guard itself failed (%s: %s). Report this instead of retrying."
              % (type(error).__name__, error), file=sys.stderr)
        return 2
    if reason:
        print("Blocked by .claude/hooks/guard_git.py: %s. %s Do not rephrase the command to get around this."
              % (reason, HOW_TO), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
