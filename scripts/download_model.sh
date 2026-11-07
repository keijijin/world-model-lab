#!/usr/bin/env bash
# Unsloth の GGUF 版 Qwen-AgentWorld-35B-A3B をダウンロードする（約22GB）
set -euo pipefail
cd "$(dirname "$0")/.."
QUANT="${1:-UD-Q4_K_M}"
FILE="Qwen-AgentWorld-35B-A3B-${QUANT}.gguf"
mkdir -p models
curl -L -C - --fail -o "models/${FILE}" \
  "https://huggingface.co/unsloth/Qwen-AgentWorld-35B-A3B-GGUF/resolve/main/${FILE}"
ls -lh "models/${FILE}"
