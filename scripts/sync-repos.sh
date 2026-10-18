#!/usr/bin/env bash
# Clone or update every OMS repo into ./repos (kept as siblings so the
# Gradle composite build `includeBuild('../oms-core')` keeps working).
#
# Usage: ./scripts/sync-repos.sh          # HTTPS
#        GIT_PROTOCOL=ssh ./scripts/sync-repos.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIST="$ROOT/repos.txt"
DEST="$ROOT/repos"
mkdir -p "$DEST"

while read -r repo; do
  [[ -z "$repo" || "$repo" == \#* ]] && continue
  name="${repo#*/}"
  if [[ "${GIT_PROTOCOL:-https}" == "ssh" ]]; then
    url="git@github.com:${repo}.git"
  else
    url="https://github.com/${repo}.git"
  fi

  if [[ -d "$DEST/$name/.git" ]]; then
    echo "↻ updating $name"
    git -C "$DEST/$name" pull --ff-only || echo "  ! could not fast-forward $name (local changes?)"
  else
    echo "↓ cloning  $name"
    git clone "$url" "$DEST/$name"
  fi
done < "$LIST"

echo "Done. Repos in $DEST"
