#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASES_DIR="$ROOT_DIR/releases"
STAGING_DIR="$RELEASES_DIR/interactive_annotation_bundle"
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_PATH="$RELEASES_DIR/interactive_annotation_bundle_${STAMP}.zip"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR" "$STAGING_DIR/data/lineages_current" "$RELEASES_DIR"
mkdir -p "$STAGING_DIR/frontend/src" "$STAGING_DIR/frontend/public" "$STAGING_DIR/sample_data" "$STAGING_DIR/scripts"

cp "$ROOT_DIR/docker-compose.yml" "$STAGING_DIR/"
cp "$ROOT_DIR/Makefile" "$STAGING_DIR/"
cp "$ROOT_DIR/README.md" "$STAGING_DIR/"
cp "$ROOT_DIR/.dockerignore" "$STAGING_DIR/"
cp -R "$ROOT_DIR/sample_data/." "$STAGING_DIR/sample_data"
mkdir -p "$STAGING_DIR/backend"
cp "$ROOT_DIR/backend/Dockerfile" "$STAGING_DIR/backend/"
cp "$ROOT_DIR/backend/README.md" "$STAGING_DIR/backend/"
cp "$ROOT_DIR/backend/requirements.txt" "$STAGING_DIR/backend/"
cp -R "$ROOT_DIR/backend/app" "$STAGING_DIR/backend/"
cp "$ROOT_DIR/scripts/release_test_bundle.sh" "$STAGING_DIR/scripts/"
cp "$ROOT_DIR/frontend/Dockerfile" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/index.html" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/nginx.conf" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/package.json" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/package-lock.json" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/tsconfig.json" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/tsconfig.node.json" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/vite.config.ts" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/vite.config.js" "$STAGING_DIR/frontend/"
cp "$ROOT_DIR/frontend/vite.config.d.ts" "$STAGING_DIR/frontend/"
cp -R "$ROOT_DIR/frontend/src/." "$STAGING_DIR/frontend/src"

rm -rf "$STAGING_DIR/backend/__pycache__"

find "$STAGING_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$STAGING_DIR" -name "*.pyc" -delete
find "$STAGING_DIR" -name ".DS_Store" -delete
find "$STAGING_DIR" -name "*.tsbuildinfo" -delete

(cd "$RELEASES_DIR" && zip -rq "$ARCHIVE_PATH" "$(basename "$STAGING_DIR")")

echo "Created release bundle:"
echo "$ARCHIVE_PATH"
