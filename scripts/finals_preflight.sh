#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_PREFIX="${PROJECT_ROOT}/env"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-6006}"
BASE_URL="${BASE_URL:-http://${HOST}:${PORT}}"
PREFLIGHT_TEXT="${PREFLIGHT_TEXT:-灵山大佛的历史背景是什么？}"

cd "${PROJECT_ROOT}"

fail() {
  echo "[FAIL] $1"
  exit 1
}

pass() {
  echo "[PASS] $1"
}

[ -d "${ENV_PREFIX}" ] || fail "Missing env at ${ENV_PREFIX}. Run scripts/autodl_prepare.sh first."
command -v conda >/dev/null 2>&1 || fail "conda was not found."
command -v curl >/dev/null 2>&1 || fail "curl was not found."

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi >/dev/null
  pass "NVIDIA GPU is visible"
else
  fail "nvidia-smi was not found; the 4090 runtime is not visible."
fi

run_cli() {
  conda run -p "${ENV_PREFIX}" python -m app.cli "$@"
}

run_cli runtime-health --profile full --quiet
pass "Runtime health check passed"

run_cli doctor >/tmp/human_doctor.json
pass "Doctor check completed"

if [ -f "reports/unified_eval_report.json" ]; then
  run_cli eval-unified --limit 30 --no-fail --report reports/preflight_eval_report.json --markdown-report reports/preflight_eval_report.md >/tmp/human_preflight_eval.json
  pass "Unified eval smoke check completed"
else
  echo "[WARN] reports/unified_eval_report.json is missing; run full eval before the final presentation."
fi

conda run -p "${ENV_PREFIX}" python - <<'PY'
import asyncio
import edge_tts

async def main():
    communicate = edge_tts.Communicate("你好，欢迎来到灵山胜境。", "zh-CN-XiaoxiaoNeural")
    chunks = 0
    async for _ in communicate.stream():
        chunks += 1
        if chunks >= 1:
            break

asyncio.run(main())
PY
pass "Edge-TTS network smoke check passed"

curl --fail --silent --show-error "${BASE_URL}/health" >/tmp/human_health.json
pass "HTTP health endpoint is reachable at ${BASE_URL}/health"

echo "[INFO] Running one short full-chain text interaction. This also warms up TTS/avatar."
curl --fail --silent --show-error \
  -F "text=${PREFLIGHT_TEXT}" \
  -F "gps_status=normal" \
  "${BASE_URL}/api/v1/interact/text" >/tmp/human_interact.json
conda run -p "${ENV_PREFIX}" python - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("/tmp/human_interact.json").read_text(encoding="utf-8"))
if not payload.get("assistant_text"):
    raise SystemExit("assistant_text is missing")
if not payload.get("audio_url"):
    raise SystemExit("audio_url is missing")
print("[PASS] Text interaction returned answer and audio")
if payload.get("video_stream_url"):
    print("[PASS] Avatar video URL returned")
else:
    print("[WARN] Avatar video URL missing; check GPU logs before going on stage")
PY

echo "[SUCCESS] Finals preflight completed for ${BASE_URL}"
