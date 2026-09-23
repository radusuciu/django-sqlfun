# List available recipes
default:
    @just --list

# Preview the changelog entries for unreleased commits
changelog:
    uv run git-cliff --unreleased

# Cut a release: bump the version, update CHANGELOG.md, tag, and push (part: patch, minor, or major)
[confirm("This tags and pushes a release, which publishes to PyPI. Continue?")]
release part:
    #!/usr/bin/env bash
    set -euo pipefail

    if [ "$(git branch --show-current)" != main ]; then
        echo "error: releases are cut from main" >&2; exit 1
    fi
    # Untracked files (e.g. local docs/) are fine; modified tracked files are not.
    if ! git diff --quiet HEAD; then
        echo "error: tracked files have uncommitted changes" >&2; exit 1
    fi
    git pull --ff-only

    # Updates pyproject.toml and re-locks uv.lock.
    new=$(uv version --bump {{part}} --short)
    # Only the new section is generated; older sections are left untouched.
    uv run git-cliff --unreleased --tag "$new" --prepend CHANGELOG.md

    # Unconventional message so git-cliff filters the release commit out.
    git commit -am "release $new"
    git tag -a "$new" -m "$new"
    git push --atomic origin main "$new"
