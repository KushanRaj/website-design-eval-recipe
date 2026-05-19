#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAMESPACE="${WDE_IMAGE_NAMESPACE:-ghcr.io/kushanraj}"
AGENT_IMAGE="${WDE_AGENT_IMAGE:-$IMAGE_NAMESPACE/wde-agent-claude:latest}"
VERIFIER_IMAGE="${WDE_VERIFIER_IMAGE:-$IMAGE_NAMESPACE/wde-verifier:latest}"
PUSH_IMAGE="${WDE_PUSH_IMAGE:-0}"
DOCKER_PLATFORM="${WDE_DOCKER_PLATFORM:-linux/amd64}"

cd "$REPO_ROOT"

echo "Building Claude agent image: $AGENT_IMAGE"
WDE_AGENT_IMAGE="$AGENT_IMAGE" \
WDE_PUSH_IMAGE="$PUSH_IMAGE" \
WDE_DOCKER_PLATFORM="$DOCKER_PLATFORM" \
bash "$REPO_ROOT/agent-image/build.sh"

echo "Building verifier image: $VERIFIER_IMAGE"
WDE_VERIFIER_IMAGE="$VERIFIER_IMAGE" \
WDE_PUSH_IMAGE="$PUSH_IMAGE" \
WDE_DOCKER_PLATFORM="$DOCKER_PLATFORM" \
bash "$REPO_ROOT/verifier-image/build.sh"

cat <<EOF
Harbor images ready.

Agent image:
  $AGENT_IMAGE

Verifier image:
  $VERIFIER_IMAGE

Package the synthetic dataset with:
  python scripts/package_synthetic_dataset.py \\
    --source-root Generator/output/harbor-dataset \\
    --dataset-dir datasets/synthetic-website-replication \\
    --dataset-name proximal/synthetic-website-replication \\
    --agent-base-image "$AGENT_IMAGE" \\
    --verifier-base-image "$VERIFIER_IMAGE" \\
    --metric-profile full-vlm \\
    --verifier-allow-internet \\
    --force
EOF
