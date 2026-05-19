#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

AGENT_IMAGE="${WDE_AGENT_IMAGE:-website-design-eval-agent-claude:latest}"
IMAGE_NAME="${WDE_VERIFIER_IMAGE:-website-design-eval-verifier:latest}"
SYNTHETIC_SITE_ROOT="${WDE_SYNTHETIC_SITE_ROOT:-Generator/output/harbor-dataset}"
DATASET_DIR="${WDE_HARBOR_DATASET_DIR:-datasets/synthetic-website-replication}"
DATASET_NAME="${WDE_HARBOR_DATASET_NAME:-proximal/synthetic-website-replication}"
PACKAGE_SYNTHETIC_DATASET="${WDE_PACKAGE_SYNTHETIC_DATASET:-1}"
BUILD_AGENT_IMAGE="${WDE_BUILD_AGENT_IMAGE:-1}"
BUILDX_BUILDER="${WDE_BUILDX_BUILDER:-default}"
DOCKER_PLATFORM="${WDE_DOCKER_PLATFORM:-linux/amd64}"

if [[ -z "${OPENAI_API_KEY:-}" && -z "${WDE_MODAL_SECRET_NAME:-}" ]]; then
  cat >&2 <<'EOF'
Warning: OPENAI_API_KEY is not set locally. Setup can continue, but actual full
reward runs need it either in .env, exported, or provided through a Modal secret.
EOF
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${WDE_MODAL_SECRET_NAME:-}" ]]; then
  cat >&2 <<'EOF'
Warning: ANTHROPIC_API_KEY is not set locally. Setup can continue, but actual
full reward runs need it either in .env, exported, or provided through a Modal
secret.
EOF
fi

if ! command -v harbor >/dev/null 2>&1; then
  cat >&2 <<'EOF'
The harbor CLI is required to build the local synthetic dataset manifest.
Install/activate Harbor before running this setup.
EOF
  exit 1
fi

if ! docker buildx inspect "$BUILDX_BUILDER" >/dev/null 2>&1; then
  echo "Docker buildx builder '$BUILDX_BUILDER' is not available." >&2
  exit 1
fi

if [[ "$BUILD_AGENT_IMAGE" = "1" ]]; then
  echo "Building reusable Harbor Claude agent image: $AGENT_IMAGE"
  WDE_AGENT_IMAGE="$AGENT_IMAGE" \
  WDE_DOCKER_PLATFORM="$DOCKER_PLATFORM" \
  bash "$REPO_ROOT/agent-image/build.sh"
fi

echo "Building reusable Harbor verifier image: $IMAGE_NAME"
WDE_VERIFIER_IMAGE="$IMAGE_NAME" \
WDE_DOCKER_PLATFORM="$DOCKER_PLATFORM" \
bash "$REPO_ROOT/verifier-image/build.sh"

if [[ "$PACKAGE_SYNTHETIC_DATASET" = "1" ]]; then
  echo "Packaging synthetic Harbor dataset: $DATASET_DIR"
  python "$REPO_ROOT/scripts/package_synthetic_dataset.py" \
    --source-root "$SYNTHETIC_SITE_ROOT" \
    --dataset-dir "$DATASET_DIR" \
    --dataset-name "$DATASET_NAME" \
    --agent-base-image "$AGENT_IMAGE" \
    --verifier-base-image "$IMAGE_NAME" \
    --metric-profile full-vlm \
    --verifier-allow-internet \
    --force
fi

cat <<EOF
Harbor VM setup complete.

Verifier image:
  $IMAGE_NAME

Agent image:
  $AGENT_IMAGE

Synthetic dataset:
  $DATASET_DIR

Default Harbor run:
  scripts/run_harbor_full_reward.sh "$DATASET_DIR"

Useful overrides:
  WDE_VERIFIER_IMAGE=your-image:tag
  WDE_AGENT_IMAGE=your-agent-image:tag
  WDE_BUILD_AGENT_IMAGE=1
  WDE_SYNTHETIC_SITE_ROOT=Generator/output/harbor-dataset
  WDE_HARBOR_DATASET_DIR=datasets/synthetic-website-replication
  WDE_HARBOR_DATASET_NAME=proximal/synthetic-website-replication
  WDE_BUILDX_BUILDER=default
  WDE_DOCKER_PLATFORM=linux/amd64
  WDE_DREAMSIM_TYPE=ensemble
  WDE_PRELOAD_MODELS=1
  WDE_VERIFY_MODEL_LOAD=1
  WDE_PACKAGE_SYNTHETIC_DATASET=0
EOF
