#!/usr/bin/env bash
# Prints the version to release from HEAD, or nothing if there's nothing to release.
#
# The bump is the largest release:major/minor/patch label among the pull requests
# merged since the last release, so a run that's skipped or cancelled is caught up
# by the next one. release:none pull requests don't release on their own.
set -euo pipefail

latest=$(git tag --list 'v*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n 1 || true)

if [ -z "$latest" ]; then
  echo 1.0.0
  exit 0
fi

bump=0

for sha in $(git rev-list --first-parent "$latest..HEAD"); do
  labels=$(gh api "repos/$GITHUB_REPOSITORY/commits/$sha/pulls" \
    --jq '.[] | select(.merged_at != null) | .labels[].name')

  for label in $labels; do
    case $label in
      release:major) level=3 ;;
      release:minor) level=2 ;;
      release:patch) level=1 ;;
      *) level=0 ;;
    esac

    if ((level > bump)); then
      bump=$level
    fi
  done
done

IFS=. read -r major minor patch <<< "${latest#v}"

case $bump in
  3) echo "$((major + 1)).0.0" ;;
  2) echo "$major.$((minor + 1)).0" ;;
  1) echo "$major.$minor.$((patch + 1))" ;;
esac
