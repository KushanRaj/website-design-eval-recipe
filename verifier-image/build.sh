#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAME="${WDE_VERIFIER_IMAGE:-website-design-eval-verifier:latest}"
DREAMSIM_TYPE="${WDE_DREAMSIM_TYPE:-ensemble}"
PRELOAD_MODELS="${WDE_PRELOAD_MODELS:-1}"
VERIFY_MODEL_LOAD="${WDE_VERIFY_MODEL_LOAD:-1}"
BUILD_ROOT="${WDE_VERIFIER_BUILD_ROOT:-$REPO_ROOT/.harbor-verifier-build}"
CONTEXT_DIR="$BUILD_ROOT/context"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to build the Harbor verifier image." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "docker is installed but the daemon is not reachable." >&2
  exit 1
fi

rm -rf "$CONTEXT_DIR"
mkdir -p \
  "$CONTEXT_DIR/verifier-image" \
  "$CONTEXT_DIR/website_design_eval" \
  "$CONTEXT_DIR/research/source-repos"

copy_dir() {
  local src="$1"
  local dst="$2"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '__pycache__' \
      --exclude '.pytest_cache' \
      --exclude '*.pyc' \
      "$src/" "$dst/"
  else
    rm -rf "$dst"
    mkdir -p "$(dirname "$dst")"
    cp -R "$src" "$dst"
    find "$dst" -name '__pycache__' -type d -prune -exec rm -rf {} +
    find "$dst" -name '.pytest_cache' -type d -prune -exec rm -rf {} +
    find "$dst" -name '*.pyc' -type f -delete
  fi
}

copy_dir "$REPO_ROOT/website_design_eval" "$CONTEXT_DIR/website_design_eval"
copy_dir "$REPO_ROOT/research/source-repos/dreamsim" "$CONTEXT_DIR/research/source-repos/dreamsim"
copy_dir "$REPO_ROOT/research/source-repos/naturalcc" "$CONTEXT_DIR/research/source-repos/naturalcc"
cp "$SCRIPT_DIR/Dockerfile" "$CONTEXT_DIR/verifier-image/Dockerfile"
cp "$SCRIPT_DIR/requirements.txt" "$CONTEXT_DIR/verifier-image/requirements.txt"
cp "$SCRIPT_DIR/setup_models.py" "$CONTEXT_DIR/verifier-image/setup_models.py"

docker build \
  -f "$CONTEXT_DIR/verifier-image/Dockerfile" \
  -t "$IMAGE_NAME" \
  --build-arg "WDE_DREAMSIM_TYPE=$DREAMSIM_TYPE" \
  --build-arg "WDE_PRELOAD_MODELS=$PRELOAD_MODELS" \
  --build-arg "WDE_VERIFY_MODEL_LOAD=$VERIFY_MODEL_LOAD" \
  "$CONTEXT_DIR"

cat <<EOF
Built Harbor verifier image: $IMAGE_NAME

Package a task against this image with:
  python scripts/package_synthetic_dataset.py \\
    --source-root Generator/output/harbor-dataset \\
    --dataset-dir datasets/synthetic-website-replication \\
    --dataset-name proximal/synthetic-website-replication \\
    --verifier-base-image "$IMAGE_NAME" \\
    --metric-profile full-vlm \\
    --verifier-allow-internet \\
    --force
EOF
