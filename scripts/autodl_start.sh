#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_PREFIX="${PROJECT_ROOT}/env"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-6006}"

export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-${PROJECT_ROOT}/.conda_pkgs}"
export AVATAR_DEVICE="${AVATAR_DEVICE:-cuda}"
export AVATAR_TORCH_DTYPE="${AVATAR_TORCH_DTYPE:-bfloat16}"
export AVATAR_WARMUP_SECONDS="${AVATAR_WARMUP_SECONDS:-0.5}"
export AVATAR_CUDA_ALLOC_CONF="${AVATAR_CUDA_ALLOC_CONF:-expandable_segments:True,max_split_size_mb:128}"
export AVATAR_VIDEO_CRF="${AVATAR_VIDEO_CRF:-20}"
export EMBEDDING_DEVICE="${EMBEDDING_DEVICE:-cpu}"

cd "${PROJECT_ROOT}"

if ! command -v conda >/dev/null 2>&1; then
  if [ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]; then
    # shellcheck source=/dev/null
    source "${HOME}/miniconda3/etc/profile.d/conda.sh"
  elif [ -f "${HOME}/anaconda3/etc/profile.d/conda.sh" ]; then
    # shellcheck source=/dev/null
    source "${HOME}/anaconda3/etc/profile.d/conda.sh"
  fi
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "[ERROR] conda was not found. Run scripts/autodl_prepare.sh in a conda-enabled AutoDL image first."
  exit 1
fi

if [ ! -d "${ENV_PREFIX}" ]; then
  echo "[ERROR] Missing env at ${ENV_PREFIX}. Run: bash scripts/autodl_prepare.sh"
  exit 1
fi

echo "[INFO] Starting Human demo on ${HOST}:${PORT}"
echo "[INFO] AutoDL custom service should point to instance port ${PORT}."
echo "[INFO] Fallback SSH tunnel: ssh -CNg -L ${PORT}:127.0.0.1:${PORT} root@<AutoDL_HOST> -p <SSH_PORT>"

conda run -p "${ENV_PREFIX}" python -m app.cli start --host "${HOST}" --port "${PORT}"
