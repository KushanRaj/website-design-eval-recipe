#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAME="${WDE_AGENT_IMAGE:-website-design-eval-agent-claude:latest}"
PUSH_IMAGE="${WDE_PUSH_IMAGE:-0}"
DOCKER_PLATFORM="${WDE_DOCKER_PLATFORM:-linux/amd64}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to build the Harbor agent image." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "docker is installed but the daemon is not reachable." >&2
  exit 1
fi

if [[ "$PUSH_IMAGE" = "1" ]]; then
  docker buildx build \
    --platform "$DOCKER_PLATFORM" \
    -f "$SCRIPT_DIR/Dockerfile" \
    -t "$IMAGE_NAME" \
    --push \
    "$REPO_ROOT"
else
  docker buildx build \
    --platform "$DOCKER_PLATFORM" \
    -f "$SCRIPT_DIR/Dockerfile" \
    -t "$IMAGE_NAME" \
    --load \
    "$REPO_ROOT"
fi

cat <<EOF
Built Harbor Claude agent image: $IMAGE_NAME

Use with:
  WDE_AGENT_IMAGE=$IMAGE_NAME
  WDE_HARBOR_AGENT_IMPORT_PATH=harbor_preinstalled_claude:PreinstalledClaudeCode
EOF
