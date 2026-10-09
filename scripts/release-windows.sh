#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
version="${1:-}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Usage: bash scripts/release-windows.sh MAJOR.MINOR.PATCH'; exit 1; }
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo 'Commit your source changes before publishing a release.'; exit 1; }
[[ -z "$(git ls-files --others --exclude-standard -- bin src desktop packaging scripts .github)" ]] || { echo 'Commit new application/build files before publishing a release.'; exit 1; }
[[ "$(git branch --show-current)" == main ]] || { echo 'Publish from main.'; exit 1; }
tag="vastgame-v$version"
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && { echo 'That release version already exists.'; exit 1; }
# The workflow builds on Windows and binds its executable to this exact source commit.
# The workflow publishes only the public allowlisted package, never account bundles.
git push origin main
git tag "$tag"
git push origin "$tag"
printf 'GitHub is building the release. Your friend then runs: vastgame update\n%s\n' 'https://github.com/Ranitayer/Vastgame/actions/workflows/windows-release.yml'
