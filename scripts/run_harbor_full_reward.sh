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
AGENT_IMPORT_PATH="${WDE_HARBOR_AGENT_IMPORT_PATH:-}"
MODEL="${WDE_HARBOR_MODEL:-${ANTHROPIC_MODEL:-claude-opus-4-7}}"
JOB_NAME="${WDE_HARBOR_JOB_NAME:-harbor-full-reward}"
JOBS_DIR="${WDE_HARBOR_JOBS_DIR:-jobs/harbor-full-reward}"
BUILDX_BUILDER="${WDE_BUILDX_BUILDER:-default}"
HARBOR_ENV="${WDE_HARBOR_ENV:-}"
MODAL_SECRET_NAME="${WDE_MODAL_SECRET_NAME:-}"
MODAL_ENVIRONMENT_NAME="${WDE_MODAL_ENVIRONMENT:-}"
MODAL_REGISTRY_SECRET_NAME="${WDE_MODAL_REGISTRY_SECRET_NAME:-}"
VERIFIER_TIMEOUT_MULTIPLIER="${WDE_HARBOR_VERIFIER_TIMEOUT_MULTIPLIER:-3}"

if [[ -n "$MODAL_ENVIRONMENT_NAME" ]]; then
  export MODAL_ENVIRONMENT="$MODAL_ENVIRONMENT_NAME"
fi

if [[ -z "${OPENAI_API_KEY:-}" && -z "$MODAL_SECRET_NAME" ]]; then
  echo "OPENAI_API_KEY is required for the full reward VLM scorer." >&2
  exit 1
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "$MODAL_SECRET_NAME" ]]; then
  echo "ANTHROPIC_API_KEY is required for candidate manifest planning in the verifier." >&2
  exit 1
fi

verifier_env=()
if [[ -z "$MODAL_SECRET_NAME" && -n "${OPENAI_API_KEY:-}" ]]; then
  verifier_env+=(--ve "OPENAI_API_KEY=$OPENAI_API_KEY")
fi
if [[ -z "$MODAL_SECRET_NAME" && -n "${ANTHROPIC_API_KEY:-}" ]]; then
  verifier_env+=(--ve "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
fi
if [[ -n "${OPENAI_BASE_URL:-}" ]]; then
  verifier_env+=(--ve "OPENAI_BASE_URL=$OPENAI_BASE_URL")
fi
if [[ -n "${ANTHROPIC_BASE_URL:-}" ]]; then
  verifier_env+=(--ve "ANTHROPIC_BASE_URL=$ANTHROPIC_BASE_URL")
fi

agent_env=()
if [[ "$AGENT" = "claude-code" || -n "$AGENT_IMPORT_PATH" ]]; then
  if [[ -z "$MODAL_SECRET_NAME" && -n "${ANTHROPIC_API_KEY:-}" ]]; then
    agent_env+=(--ae "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
  fi
  if [[ -n "${ANTHROPIC_BASE_URL:-}" ]]; then
    agent_env+=(--ae "ANTHROPIC_BASE_URL=$ANTHROPIC_BASE_URL")
  fi
  if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    agent_env+=(--ae "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN")
  fi
fi

agent_args=()
if [[ -n "$AGENT_IMPORT_PATH" ]]; then
  agent_args+=(--agent-import-path "$AGENT_IMPORT_PATH")
else
  agent_args+=(--agent "$AGENT")
fi

environment_args=()
if [[ -n "$HARBOR_ENV" ]]; then
  environment_args+=(--env "$HARBOR_ENV")
fi
if [[ -n "$MODAL_SECRET_NAME" ]]; then
  environment_args+=(--ek "secrets=[\"$MODAL_SECRET_NAME\"]")
fi
if [[ -n "$MODAL_REGISTRY_SECRET_NAME" ]]; then
  environment_args+=(--ek "registry_secret=\"$MODAL_REGISTRY_SECRET_NAME\"")
fi
if [[ -n "${WDE_HARBOR_OVERRIDE_MEMORY_MB:-}" ]]; then
  environment_args+=(--override-memory "$WDE_HARBOR_OVERRIDE_MEMORY_MB")
fi
if [[ -n "${WDE_HARBOR_OVERRIDE_CPUS:-}" ]]; then
  environment_args+=(--override-cpus "$WDE_HARBOR_OVERRIDE_CPUS")
fi

if [[ "${WDE_SKIP_BUILDX_CHECK:-0}" != "1" && "$HARBOR_ENV" != "modal" ]]; then
  if ! docker buildx inspect "$BUILDX_BUILDER" >/dev/null 2>&1; then
    echo "Docker buildx builder '$BUILDX_BUILDER' is not available." >&2
    exit 1
  fi
fi

export BUILDX_BUILDER

cmd=(
  harbor run
  --path "$TARGET_PATH"
  "${agent_args[@]}"
  --model "$MODEL"
  --n-concurrent "${WDE_HARBOR_N_CONCURRENT:-1}"
  --job-name "$JOB_NAME"
  --jobs-dir "$JOBS_DIR"
  --yes
)
if [[ -n "${WDE_HARBOR_TIMEOUT_MULTIPLIER:-}" ]]; then
  cmd+=(--timeout-multiplier "$WDE_HARBOR_TIMEOUT_MULTIPLIER")
fi
if [[ -n "${WDE_HARBOR_AGENT_TIMEOUT_MULTIPLIER:-}" ]]; then
  cmd+=(--agent-timeout-multiplier "$WDE_HARBOR_AGENT_TIMEOUT_MULTIPLIER")
fi
if [[ -n "$VERIFIER_TIMEOUT_MULTIPLIER" ]]; then
  cmd+=(--verifier-timeout-multiplier "$VERIFIER_TIMEOUT_MULTIPLIER")
fi
if [[ -n "${WDE_HARBOR_ENVIRONMENT_BUILD_TIMEOUT_MULTIPLIER:-}" ]]; then
  cmd+=(--environment-build-timeout-multiplier "$WDE_HARBOR_ENVIRONMENT_BUILD_TIMEOUT_MULTIPLIER")
fi
if ((${#environment_args[@]})); then
  cmd+=("${environment_args[@]}")
fi
if ((${#verifier_env[@]})); then
  cmd+=("${verifier_env[@]}")
fi
if ((${#agent_env[@]})); then
  cmd+=("${agent_env[@]}")
fi
cmd+=("$@")

"${cmd[@]}"
