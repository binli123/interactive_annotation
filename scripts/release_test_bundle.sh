#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASES_DIR="$ROOT_DIR/releases"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/interactive_annotation_release_test.XXXXXX")"
PORT="${INTERACTIVE_ANNOTATION_TEST_PORT:-5183}"
PROJECT="interactive_annotation_release_test"
export COMPOSE_BAKE=false

cleanup() {
  if [[ -d "$TEST_ROOT/interactive_annotation_bundle" ]]; then
    (
      cd "$TEST_ROOT/interactive_annotation_bundle" && \
      INTERACTIVE_ANNOTATION_PORT="$PORT" COMPOSE_PROJECT_NAME="$PROJECT" docker compose down </dev/null >/dev/null 2>&1 || true
    )
  fi
}
trap cleanup EXIT

bash "$ROOT_DIR/scripts/create_release_bundle.sh" >/dev/null

LATEST_ZIP="$(ls -t "$RELEASES_DIR"/interactive_annotation_bundle_*.zip | head -n 1)"
if [[ -z "${LATEST_ZIP:-}" ]]; then
  echo "No release zip was created."
  exit 1
fi

unzip -q "$LATEST_ZIP" -d "$TEST_ROOT"
cd "$TEST_ROOT/interactive_annotation_bundle"

INTERACTIVE_ANNOTATION_PORT="$PORT" COMPOSE_PROJECT_NAME="$PROJECT" docker compose up -d --build </dev/null

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null
curl -fsS "http://127.0.0.1:${PORT}/api/health"

echo
echo "Release bundle smoke test passed."
echo "Bundle zip: $LATEST_ZIP"
echo "Temporary unpack dir: $TEST_ROOT"
