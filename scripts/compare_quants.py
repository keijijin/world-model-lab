"""同じ quant_probe を量子化ごとに採点する。

チェックリストの IQ4_XS / Q5 / Q8 は、Unsloth のファイル名では
UD-IQ4_XS / UD-Q5_K_M / Q8_0 である。ファイルが物理メモリの 80% 以上なら
ロードしない。36GiB のマシンでは Q8_0（約 34GiB）がこの条件に当たる。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenario_runner import RESULTS, load_catalog, run_scenario  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MEMORY_RATIO = 0.80
QUANTS = [
    {"label": "IQ4_XS", "file_quant": "UD-IQ4_XS"},
    {"label": "Q5", "file_quant": "UD-Q5_K_M"},
    {"label": "Q8", "file_quant": "Q8_0"},
]
REPO = "https://huggingface.co/unsloth/Qwen-AgentWorld-35B-A3B-GGUF/resolve/main"


def fits_in_memory(file_bytes, ram_bytes, ratio=MEMORY_RATIO):
    return file_bytes < ram_bytes * ratio


def ram_bytes():
    raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
    return int(raw)


def remote_size(file_quant):
    name = f"Qwen-AgentWorld-35B-A3B-{file_quant}.gguf"
    request = urllib.request.Request(f"{REPO}/{name}", method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        length = response.headers.get("Content-Length")
    if not length:
        raise RuntimeError(f"Content-Length が無い: {name}")
    return name, int(length)


def gib(n):
    return n / 1024 ** 3


def listener_pids():
    result = subprocess.run(
        ["lsof", "-tiTCP:8080", "-sTCP:LISTEN"],
        text=True,
        capture_output=True,
    )
    return [int(line) for line in result.stdout.split() if line.strip()]


def stop_server():
    pids = listener_pids()
    if not pids:
        return
    print(f"port 8080 を停止: {pids}")
    for pid in pids:
        subprocess.run(["kill", str(pid)], check=False)
    for _ in range(50):
        if not listener_pids():
            return
        time.sleep(0.2)
    for pid in listener_pids():
        subprocess.run(["kill", "-9", str(pid)], check=False)


def wait_health(timeout):
    deadline = time.time() + timeout
    url = "http://127.0.0.1:8080/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2)
    return False


def start_server(file_quant):
    log_path = RESULTS / f"llama_{file_quant}.log"
    RESULTS.mkdir(exist_ok=True)
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [str(ROOT / "scripts" / "start_server.sh"), file_quant],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    if not wait_health(300):
        proc.kill()
        tail = log_path.read_text()[-2000:]
        raise RuntimeError(f"{file_quant} が 300 秒以内に応答しない\n{tail}")
    return proc


def ensure_download(file_quant):
    name = f"Qwen-AgentWorld-35B-A3B-{file_quant}.gguf"
    path = ROOT / "models" / name
    if path.exists() and path.stat().st_size > 0:
        return path
    subprocess.run([str(ROOT / "scripts" / "download_model.sh"), file_quant], cwd=ROOT, check=True)
    return path


def preflight():
    ram = ram_bytes()
    rows = []
    for spec in QUANTS:
        name, size = remote_size(spec["file_quant"])
        ok = fits_in_memory(size, ram)
        rows.append({
            "label": spec["label"],
            "file_quant": spec["file_quant"],
            "file": name,
            "bytes": size,
            "gib": round(gib(size), 2),
            "ram_gib": round(gib(ram), 2),
            "load": ok,
            "reason": None if ok else (
                f"GGUF {gib(size):.2f} GiB は物理メモリ {gib(ram):.2f} GiB の {MEMORY_RATIO:.0%} 以上"
            ),
        })
    return rows


def write_summary(rows):
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = RESULTS / f"quant_compare_{stamp}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "label\tfile\tGiB\tload\tpassed\ttok/s\tsec/turn\tfirst_failure\treason",
    ]
    for row in rows:
        score = ""
        if row.get("passed") is not None:
            score = f"{row['passed']}/{row['total']}"
        lines.append(
            "\t".join([
                row["label"],
                row["file_quant"],
                str(row.get("gib", "")),
                "yes" if row.get("load") else "no",
                score,
                str(row.get("tok_per_sec", "")),
                str(row.get("sec_per_turn", "")),
                str(row.get("first_failure", "")),
                row.get("reason") or "",
            ])
        )
    text_path = RESULTS / f"quant_compare_{stamp}.txt"
    text_path.write_text("\n".join(lines) + "\n")
    print(text_path.read_text())
    print(path)
    return path


def metrics(summary):
    turns = [turn for turn in summary["turns"] if "seconds" in turn]
    seconds = sum(turn["seconds"] for turn in turns)
    tokens = sum(turn.get("completion_tokens") or 0 for turn in turns)
    return {
        "passed": summary["passed"],
        "total": summary["total"],
        "first_failure": summary["first_failure"],
        "sec_per_turn": round(seconds / len(turns), 1) if turns else None,
        "tok_per_sec": round(tokens / seconds, 1) if seconds else None,
    }


def main():
    parser = argparse.ArgumentParser(description="量子化ごとの精度と速度")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--include-running", action="store_true",
                        help="今起動中のモデルでも quant_probe を採点して表に入れる")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rows = preflight()
    if args.preflight_only:
        write_summary(rows)
        return

    scenarios, _ = load_catalog()
    probe = scenarios["quant_probe"]
    # 比較のあと、起動していた量子化へ戻す。ファイル名から UD-Q4_K_M などを取る。
    restore = None
    try:
        from scenario_runner import model_name, quant_slug
        restore = quant_slug(model_name(os.environ.get("AGENTWORLD_URL", "http://127.0.0.1:8080")))
    except Exception:
        restore = None
    try:
        _run_quant_rows(rows, probe, args)
    finally:
        if restore:
            path = ROOT / "models" / f"Qwen-AgentWorld-35B-A3B-{restore}.gguf"
            if path.exists():
                print(f"サーバーを {restore} に戻す")
                try:
                    stop_server()
                    start_server(restore)
                except Exception as exc:
                    print(f"復元に失敗: {exc}")


def _run_quant_rows(rows, probe, args):
    if args.include_running:
        try:
            summary = run_scenario(probe, os.environ.get("AGENTWORLD_URL", "http://127.0.0.1:8080"), seed=args.seed)
            rows.insert(0, {
                "label": summary["quant"],
                "file_quant": summary["quant"],
                "gib": None,
                "load": True,
                "reason": "起動中のサーバー",
                **metrics(summary),
            })
        except Exception as exc:
            rows.insert(0, {
                "label": "running",
                "file_quant": "",
                "load": False,
                "reason": str(exc),
            })

    for row in rows:
        if row["label"] not in {item["label"] for item in QUANTS}:
            continue
        if not row["load"]:
            continue
        try:
            ensure_download(row["file_quant"])
            stop_server()
            start_server(row["file_quant"])
            summary = run_scenario(probe, "http://127.0.0.1:8080", seed=args.seed)
            row.update(metrics(summary))
        except Exception as exc:
            row["reason"] = str(exc)
            row["load"] = False
    write_summary(rows)


if __name__ == "__main__":
    main()
