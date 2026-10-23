#!/usr/bin/env bash
# Sync oms-workspace and every repo in repos.txt into ./repos (kept as siblings so the
# Gradle composite build `includeBuild('../oms-core')` keeps working).
#
# For each repo:
#   - clone it if missing
#   - fetch and prune deleted remote branches
#   - main branch = the repo's GitHub default branch (develop for services, master otherwise)
#   - on the main branch            → fast-forward it (and fix its upstream if wrong)
#   - on a finished work branch     → it was pushed and is now deleted on GitHub (PR merged),
#                                     or it is pushed and fully merged into main:
#                                     switch back to main, pull, delete the local branch if merged
#   - on an active work branch      → (never pushed, or still open) leave it untouched,
#                                     only report how far it is from main
#   - other local branches whose GitHub branch is gone and that are merged → deleted
#   - uncommitted changes to tracked files → never switch branches, only report
#     (untracked files do not block: a checkout keeps them)
#
# Usage: ./scripts/sync-repos.sh            # HTTPS
#        GIT_PROTOCOL=ssh ./scripts/sync-repos.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIST="$ROOT/repos.txt"
DEST="$ROOT/repos"

if [[ -t 1 ]]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; D=""; N=""
fi
step() { echo "   ${D}→${N} $*"; }
ok()   { echo "   ${G}✓${N} $*"; }
warn() { echo "   ${Y}!${N} $*"; WARNINGS+=("$CURRENT_REPO: $*"); }
fail() { echo "   ${R}✗${N} $*"; WARNINGS+=("$CURRENT_REPO: $*"); }
WARNINGS=()
CURRENT_REPO=""

repo_url() {
  if [[ "${GIT_PROTOCOL:-https}" == "ssh" ]]; then echo "git@github.com:$1.git"; else echo "https://github.com/$1.git"; fi
}

# Default branch of origin (develop / master), detected from GitHub.
main_branch() {
  local dir=$1 b
  git -C "$dir" remote set-head origin --auto >/dev/null 2>&1
  b=$(git -C "$dir" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
  b=${b#origin/}
  echo "${b:-master}"
}

# Upstream of a local branch, e.g. "origin/develop" ("" if none).
upstream_of() { git -C "$1" for-each-ref --format='%(upstream:short)' "refs/heads/$2"; }
# "[gone]" when the upstream branch was deleted on GitHub.
upstream_track() { git -C "$1" for-each-ref --format='%(upstream:track)' "refs/heads/$2"; }

pull_main() {
  local dir=$1 main=$2 before after
  local upstream
  upstream=$(upstream_of "$dir" "$main")
  if [[ "$upstream" != "origin/$main" ]] || [[ "$(upstream_track "$dir" "$main")" == "[gone]" ]]; then
    step "upstream of $main is '${upstream:-none}', setting it to origin/$main"
    git -C "$dir" branch --quiet --set-upstream-to="origin/$main" "$main"
  fi
  before=$(git -C "$dir" rev-parse --short HEAD)
  if git -C "$dir" merge --quiet --ff-only "origin/$main" >/dev/null 2>&1; then
    after=$(git -C "$dir" rev-parse --short HEAD)
    if [[ "$before" == "$after" ]]; then ok "$main is up to date ($after)"
    else ok "$main updated $before → $after ($(git -C "$dir" rev-list --count "$before..$after") new commit(s))"; fi
  else
    fail "$main has local commits not on origin/$main — cannot fast-forward, fix manually"
  fi
}

sync_repo() {
  local dir=$1 slug=$2 main current dirty upstream_gone=0 merged=0
  CURRENT_REPO=$(basename "$dir")
  echo "${B}■ $CURRENT_REPO${N}"

  if [[ ! -d "$dir/.git" ]]; then
    step "not found, cloning $slug"
    if git clone --quiet "$(repo_url "$slug")" "$dir"; then
      ok "cloned on $(git -C "$dir" branch --show-current)"
    else
      fail "clone failed"
    fi
    return
  fi

  step "fetching (pruning branches deleted on GitHub)"
  git -C "$dir" fetch --quiet --prune origin || { fail "fetch failed"; return; }

  main=$(main_branch "$dir")
  current=$(git -C "$dir" branch --show-current)
  # Only changes to tracked files block a branch switch; untracked files survive a checkout.
  dirty=$(git -C "$dir" status --porcelain --untracked-files=no)
  local untracked
  untracked=$(git -C "$dir" ls-files --others --exclude-standard | wc -l | tr -d ' ')

  if [[ -z "$current" ]]; then
    warn "detached HEAD — left untouched"
    return
  fi
  step "main branch: $main · current branch: $current"
  (( untracked > 0 )) && step "$untracked untracked file(s) present (kept, not committed)"

  if [[ "$current" == "$main" ]]; then
    [[ -n "$dirty" ]] && step "uncommitted changes present (kept)"
    pull_main "$dir" "$main"
    cleanup_gone_branches "$dir" "$main"
    return
  fi

  # On a work branch: is it finished?
  #   gone   = it had its own branch on GitHub and that branch was deleted (PR merged + branch deleted)
  #   merged = it has its own branch on GitHub and all its commits are in origin/main
  # A branch that was never pushed (no upstream, or upstream = origin/main) is always "active".
  local upstream
  upstream=$(upstream_of "$dir" "$current")
  if [[ -n "$upstream" && "$upstream" != "origin/$main" ]]; then
    if [[ "$(upstream_track "$dir" "$current")" == "[gone]" ]]; then
      upstream_gone=1
    elif git -C "$dir" merge-base --is-ancestor HEAD "origin/$main" 2>/dev/null; then
      merged=1
    fi
  fi

  if (( upstream_gone == 0 && merged == 0 )); then
    local ahead behind
    ahead=$(git -C "$dir" rev-list --count "origin/$main..HEAD")
    behind=$(git -C "$dir" rev-list --count "HEAD..origin/$main")
    if [[ -z "$upstream" || "$upstream" == "origin/$main" ]]; then
      warn "on active branch '$current' (not pushed yet; $ahead ahead / $behind behind origin/$main) — left untouched"
    else
      warn "on active branch '$current' (open on GitHub; $ahead ahead / $behind behind origin/$main) — left untouched"
    fi
    if git -C "$dir" show-ref --verify --quiet "refs/heads/$main"; then
      git -C "$dir" fetch --quiet origin "$main:$main" 2>/dev/null && step "local $main fast-forwarded in the background"
    fi
    return
  fi

  if (( upstream_gone )); then step "'$current' was deleted on GitHub (PR merged)"
  else step "'$current' is fully merged into origin/$main"; fi

  if [[ -n "$dirty" ]]; then
    warn "'$current' is finished but has uncommitted changes — not switching. Commit/stash them, then re-run"
    return
  fi

  step "switching $current → $main"
  if ! git -C "$dir" checkout --quiet "$main" 2>/dev/null; then
    fail "could not check out $main"
    return
  fi
  pull_main "$dir" "$main"
  cleanup_gone_branches "$dir" "$main"
}

# Delete local branches whose GitHub branch is gone, if they are fully merged into main.
cleanup_gone_branches() {
  local dir=$1 main=$2 b current
  current=$(git -C "$dir" branch --show-current)
  while read -r b; do
    [[ -z "$b" || "$b" == "$main" || "$b" == "$current" ]] && continue
    [[ "$(upstream_track "$dir" "$b")" == "[gone]" ]] || continue
    if git -C "$dir" merge-base --is-ancestor "$b" "origin/$main" 2>/dev/null &&
       git -C "$dir" branch --quiet -D "$b" 2>/dev/null; then
      ok "deleted local branch '$b' (merged, gone on GitHub)"
    else
      warn "local branch '$b' is gone on GitHub but has commits not in $main — kept. Check it, then: git -C $dir branch -D $b"
    fi
  done < <(git -C "$dir" for-each-ref --format='%(refname:short)' refs/heads/)
}

main() {
  echo "${B}Syncing OMS repos${N} ${D}($ROOT)${N}"
  echo
  mkdir -p "$DEST"
  while read -r repo _; do
    [[ -z "${repo:-}" || "$repo" == \#* ]] && continue
    sync_repo "$DEST/${repo#*/}" "$repo"
    echo
  done < "$LIST"

  # The workspace itself last (its main branch is master).
  sync_repo "$ROOT" "domt97/oms-workspace"
  echo

  if (( ${#WARNINGS[@]} )); then
    echo "${Y}${B}Needs your attention:${N}"
    for w in "${WARNINGS[@]}"; do echo "  ${Y}!${N} $w"; done
  else
    echo "${G}${B}All repos synced.${N}"
  fi
}

# Everything runs from inside main(), so bash has parsed the whole file before
# this script may switch the workspace branch (which can rewrite this very file).
main "$@"; exit $?
