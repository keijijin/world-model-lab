#!/usr/bin/env bash
# llama.cpp の llama-server で OpenAI 互換 API を起動する（http://127.0.0.1:8080）
set -euo pipefail
cd "$(dirname "$0")/.."
QUANT="${1:-UD-Q4_K_M}"
CTX="${CTX:-32768}"
exec llama-server \
  -m "models/Qwen-AgentWorld-35B-A3B-${QUANT}.gguf" \
  --host 127.0.0.1 --port 8080 \
  -ngl 99 -c "${CTX}" -fa on \
  --jinja --reasoning-format deepseek
