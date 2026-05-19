#!/usr/bin/env bash
set -euo pipefail

TARGET_PATH="${1:-datasets/synthetic-website-replication}"
if [[ $# -gt 0 ]]; then
  shift
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

AGENT="${WDE_HARBOR_AGENT:-claude-code}"
MODEL="${WDE_HARBOR_MODEL:-${ANTHROPIC_MODEL:-claude-opus-4-7}}"
JOB_NAME="${WDE_HARBOR_JOB_NAME:-harbor-full-reward}"
JOBS_DIR="${WDE_HARBOR_JOBS_DIR:-jobs/harbor-full-reward}"
BUILDX_BUILDER="${WDE_BUILDX_BUILDER:-default}"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is required for the full reward VLM scorer." >&2
  exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ANTHROPIC_API_KEY is required for candidate manifest planning in the verifier." >&2
  exit 1
fi

verifier_env=(--ve "OPENAI_API_KEY=$OPENAI_API_KEY" --ve "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
if [[ -n "${OPENAI_BASE_URL:-}" ]]; then
  verifier_env+=(--ve "OPENAI_BASE_URL=$OPENAI_BASE_URL")
fi
if [[ -n "${ANTHROPIC_BASE_URL:-}" ]]; then
  verifier_env+=(--ve "ANTHROPIC_BASE_URL=$ANTHROPIC_BASE_URL")
fi

agent_env=()
if [[ "$AGENT" = "claude-code" ]]; then
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    agent_env+=(--ae "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
  fi
  if [[ -n "${ANTHROPIC_BASE_URL:-}" ]]; then
    agent_env+=(--ae "ANTHROPIC_BASE_URL=$ANTHROPIC_BASE_URL")
  fi
  if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    agent_env+=(--ae "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN")
  fi
fi

if ! docker buildx inspect "$BUILDX_BUILDER" >/dev/null 2>&1; then
  echo "Docker buildx builder '$BUILDX_BUILDER' is not available." >&2
  exit 1
fi

export BUILDX_BUILDER

harbor run \
  --path "$TARGET_PATH" \
  --agent "$AGENT" \
  --model "$MODEL" \
  --n-concurrent "${WDE_HARBOR_N_CONCURRENT:-1}" \
  --job-name "$JOB_NAME" \
  --jobs-dir "$JOBS_DIR" \
  --yes \
  "${verifier_env[@]}" \
  "${agent_env[@]}" \
  "$@"
