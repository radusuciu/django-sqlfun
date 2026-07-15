#!/bin/sh
# Refresh uv.lock after bumpver rewrites the version in pyproject.toml, and
# stage it so the bump commit (and the tag pointing at it) carries a lock
# that matches -- CI runs `uv sync --locked` and fails on a stale lock.
set -e
uv lock
git add uv.lock
