"""Qwen-AgentWorld をターミナル世界モデルとして試すスクリプト。

llama-server (OpenAI互換API, http://127.0.0.1:8080) に接続し、
複数ターンのコマンドを順に送って「予測されたターミナル出力」を表示する。
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import os

URL = os.environ.get("AGENTWORLD_URL", "http://127.0.0.1:8080") + "/v1/chat/completions"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "terminal" / "system_prompt.txt"

INITIAL_STATE = "root@demo:/app#"

# 状態の一貫性を確かめるためのシナリオ
ACTIONS = [
    "mkdir project && cd project\n",
    "echo 'hello world' > greeting.txt\n",
    "ls -la\n",
    "cat greeting.txt | wc -c\n",
    "rm greeting.txt\n",
    "cat greeting.txt\n",
]


def chat(messages):
    body = json.dumps({
        "messages": messages,
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "max_tokens": 8192,
    }).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)


def main():
    system = PROMPT_FILE.read_text()
    messages = [{"role": "system", "content": system}]
    for i, keys in enumerate(ACTIONS, 1):
        action = json.dumps([{"keystrokes": keys, "duration": 1.0}], ensure_ascii=False, indent=2)
        user = f"### Turn {i}\n"
        if i == 1:
            user += f"**Current State:**\n{INITIAL_STATE}\n\n"
        user += f"**Action:**\n```json\n{action}\n```\n**Environment Observation:**"
        messages.append({"role": "user", "content": user})

        t0 = time.time()
        res = chat(messages)
        dt = time.time() - t0
        msg = res["choices"][0]["message"]
        content = msg.get("content") or ""
        thinking = msg.get("reasoning_content") or ""
        # 思考がcontentに混ざって返る場合に備えて除去
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        usage = res.get("usage", {})
        tok = usage.get("completion_tokens", 0)

        print(f"\n===== Turn {i}: {keys.strip()} =====")
        print(f"[{dt:.1f}秒, 生成{tok}トークン, {tok / dt if dt else 0:.1f} tok/s, 思考{len(thinking)}文字]")
        print(content)
        sys.stdout.flush()
        messages.append({"role": "assistant", "content": content})


if __name__ == "__main__":
    main()
