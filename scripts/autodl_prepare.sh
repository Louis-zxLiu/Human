#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_PREFIX="${PROJECT_ROOT}/env"

export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export TORCH_WHL_INDEX_URL="${TORCH_WHL_INDEX_URL:-https://download.pytorch.org/whl/cu126}"
export OPENAI_WHISPER_REQUIREMENT="${OPENAI_WHISPER_REQUIREMENT:-openai-whisper==20250625}"
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-${PROJECT_ROOT}/.conda_pkgs}"

cd "${PROJECT_ROOT}"

if ! command -v conda >/dev/null 2>&1; then
  echo "[ERROR] conda was not found. Use an AutoDL image with conda preinstalled."
  exit 1
fi

mkdir -p "${CONDA_PKGS_DIRS}"

if [ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]; then
  # shellcheck source=/dev/null
  source "${HOME}/miniconda3/etc/profile.d/conda.sh"
elif [ -f "${HOME}/anaconda3/etc/profile.d/conda.sh" ]; then
  # shellcheck source=/dev/null
  source "${HOME}/anaconda3/etc/profile.d/conda.sh"
fi

if [ -d "${ENV_PREFIX}" ]; then
  echo "[INFO] Updating conda env at ${ENV_PREFIX}"
  conda env update -p "${ENV_PREFIX}" -f environment.yml --prune
else
  echo "[INFO] Creating conda env at ${ENV_PREFIX}"
  conda env create -p "${ENV_PREFIX}" -f environment.yml
fi

run_cli() {
  conda run -p "${ENV_PREFIX}" python -m app.cli "$@"
}

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
  echo "[INFO] Created .env from .env.example. Fill LLM_API_KEY before the full demo."
fi

echo "[INFO] Bootstrapping runtime dependencies and models"
run_cli bootstrap

echo "[INFO] Preparing behavior data and knowledge base"
run_cli prepare-data
run_cli prepare-kb

echo "[INFO] Building frontend"
run_cli build-frontend

echo "[INFO] Seeding dashboard demo logs"
run_cli seed-demo-logs --reset

if [ ! -f "tests/unified_eval_cases.jsonl" ]; then
  echo "[INFO] Generating unified eval cases"
  run_cli generate-unified-eval --target 1200 --output tests/unified_eval_cases.jsonl
fi

if [ ! -f "reports/unified_eval_report.json" ]; then
  echo "[INFO] Running unified eval report. This can take a while."
  run_cli eval-unified --report reports/unified_eval_report.json --markdown-report reports/unified_eval_report.md --strict --fail-under 90
else
  echo "[INFO] Existing unified eval report detected: reports/unified_eval_report.json"
fi

echo "[SUCCESS] AutoDL environment is prepared."
echo "[NEXT] Run: bash scripts/autodl_start.sh"
