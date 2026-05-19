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

IMAGE_NAME="${WDE_VERIFIER_IMAGE:-website-design-eval-verifier:latest}"
SYNTHETIC_SITE_ROOT="${WDE_SYNTHETIC_SITE_ROOT:-Generator/output/harbor-dataset}"
DATASET_DIR="${WDE_HARBOR_DATASET_DIR:-datasets/synthetic-website-replication}"
DATASET_NAME="${WDE_HARBOR_DATASET_NAME:-proximal/synthetic-website-replication}"
PACKAGE_SYNTHETIC_DATASET="${WDE_PACKAGE_SYNTHETIC_DATASET:-1}"
BUILDX_BUILDER="${WDE_BUILDX_BUILDER:-default}"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  cat >&2 <<'EOF'
OPENAI_API_KEY is required for the actual full reward because VLM scoring is part
of the reward. Put it in .env or export it before running this setup.
EOF
  exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  cat >&2 <<'EOF'
ANTHROPIC_API_KEY is required for the verifier-side candidate manifest planner.
Put it in .env or export it before running setup.
EOF
  exit 1
fi

if ! command -v harbor >/dev/null 2>&1; then
  cat >&2 <<'EOF'
The harbor CLI is required to build the local synthetic dataset manifest.
Install/activate Harbor before running this setup.
EOF
  exit 1
fi

echo "Building reusable Harbor verifier image: $IMAGE_NAME"
WDE_VERIFIER_IMAGE="$IMAGE_NAME" bash "$REPO_ROOT/verifier-image/build.sh"

if ! docker buildx inspect "$BUILDX_BUILDER" >/dev/null 2>&1; then
  echo "Docker buildx builder '$BUILDX_BUILDER' is not available." >&2
  exit 1
fi

if [[ "$PACKAGE_SYNTHETIC_DATASET" = "1" ]]; then
  echo "Packaging synthetic Harbor dataset: $DATASET_DIR"
  python "$REPO_ROOT/scripts/package_synthetic_dataset.py" \
    --source-root "$SYNTHETIC_SITE_ROOT" \
    --dataset-dir "$DATASET_DIR" \
    --dataset-name "$DATASET_NAME" \
    --verifier-base-image "$IMAGE_NAME" \
    --metric-profile full-vlm \
    --verifier-allow-internet \
    --force
fi

cat <<EOF
Harbor VM setup complete.

Verifier image:
  $IMAGE_NAME

Synthetic dataset:
  $DATASET_DIR

Default Harbor run:
  scripts/run_harbor_full_reward.sh "$DATASET_DIR"

Useful overrides:
  WDE_VERIFIER_IMAGE=your-image:tag
  WDE_SYNTHETIC_SITE_ROOT=Generator/output/harbor-dataset
  WDE_HARBOR_DATASET_DIR=datasets/synthetic-website-replication
  WDE_HARBOR_DATASET_NAME=proximal/synthetic-website-replication
  WDE_BUILDX_BUILDER=default
  WDE_DREAMSIM_TYPE=ensemble
  WDE_PRELOAD_MODELS=1
  WDE_VERIFY_MODEL_LOAD=1
  WDE_PACKAGE_SYNTHETIC_DATASET=0
EOF
