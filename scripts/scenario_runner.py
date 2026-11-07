"""シナリオを llama-server に流し、文字列オラクルで採点する。

世界モデルの出力は実行結果ではない。期待する断片・正規表現と突き合わせ、
どのターンで状態が崩れたかを残す。
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

TOOL_SUFFIX = """
Please analyze the input above and predict the realistic output/response that the environment would produce.

Requirements:
- Be precise and accurate in your prediction
- Consider edge cases and error conditions
- Maintain state consistency with previous interactions in this session
- Match the expected output format

First, think step by step to explain your reasoning. Then, provide the simulated environment observation wrapped strictly within the <predicted_observation></predicted_observation> tags."""

EXPECT_KEYS = {
    "include",
    "exclude",
    "include_any",
    "regex",
    "regex_any",
    "exclude_regex",
    "allow_empty",
}


def load_catalog():
    sys.path.insert(0, str(ROOT))
    from scenarios.catalog import SCENARIOS, SUITES
    return SCENARIOS, SUITES


def resolve_system(scenario):
    path = ROOT / scenario["system_prompt"]
    text = path.read_text()
    for key, spec in scenario.get("system_subs", {}).items():
        if isinstance(spec, dict) and "file" in spec:
            value = (ROOT / spec["file"]).read_text().rstrip() + "\n"
        else:
            value = str(spec)
        if key not in text:
            raise SystemExit(f"{scenario['id']}: system prompt に {key} がありません")
        text = text.replace(key, value)
    return text


def encode_action(scenario, turn):
    if "command" in turn:
        keys = turn["command"]
        if not keys.endswith("\n"):
            keys += "\n"
        payload = [{"keystrokes": keys, "duration": float(turn.get("duration", 1.0))}]
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        return body, "json"
    action = turn["action"]
    if isinstance(action, str):
        lang = turn.get("action_lang", scenario.get("action_lang", "text"))
        return action, lang
    payload = action
    if scenario.get("arguments_as_string") and isinstance(payload.get("arguments"), (dict, list)):
        payload = dict(payload)
        payload["arguments"] = json.dumps(payload["arguments"], ensure_ascii=False)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    lang = turn.get("action_lang", scenario.get("action_lang", "json"))
    return body, lang


def subst_url(action, url):
    if isinstance(action, str):
        return action.replace("{url}", url)
    if isinstance(action, list):
        return [subst_url(item, url) for item in action]
    if isinstance(action, dict):
        return {key: subst_url(value, url) for key, value in action.items()}
    return action


def first_url(text):
    match = re.search(r"https://[^\s\]\)\"'<>]+", text)
    if not match:
        return None
    return match.group(0).rstrip(".,);")


def state_for(scenario, turn, index):
    if "state" in turn:
        return turn["state"]
    if index == 1 and scenario.get("initial_state"):
        return scenario["initial_state"]
    return None


def build_user(scenario, turn, index, action_text, action_lang):
    parts = [f"### Turn {index}\n"]
    task = turn.get("task", scenario.get("task"))
    if task and scenario.get("style") == "ui":
        parts.append(f"**Task Instruction:**\n{task}\n\n")
    state = state_for(scenario, turn, index)
    if state is not None:
        parts.append(f"**Current State:**\n{state}\n\n")
    parts.append(f"**Action:**\n```{action_lang}\n{action_text}\n```")
    style = scenario["style"]
    if style == "terminal":
        parts.append("\n**Environment Observation:**")
    elif style == "tool":
        parts.append(TOOL_SUFFIX)
    else:
        parts.append("\n")
    return "".join(parts)


def observable(content):
    match = re.search(
        r"<predicted_observation>(.*?)</predicted_observation>",
        content,
        re.S | re.I,
    )
    if match and match.group(1).strip():
        return match.group(1).strip()
    return content.strip()


def _search(pattern, text):
    return re.search(pattern, text, re.M)


def evaluate(text, expect, extra_include=None):
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise ValueError(f"未知の expect キー: {sorted(unknown)}")
    failures = []
    if not text.strip() and not expect.get("allow_empty"):
        failures.append("観測が空")
    for item in expect.get("include", []):
        if item not in text:
            failures.append(f"欠落: {item!r}")
    for item in extra_include or []:
        if item not in text:
            failures.append(f"前ターンから引き継げず: {item!r}")
    for item in expect.get("exclude", []):
        if item in text:
            failures.append(f"残存: {item!r}")
    any_of = expect.get("include_any", [])
    if any_of and not any(item in text for item in any_of):
        failures.append(f"いずれも無し: {any_of!r}")
    for pattern in expect.get("regex", []):
        if _search(pattern, text) is None:
            failures.append(f"正規表現不一致: {pattern}")
    regex_any = expect.get("regex_any", [])
    if regex_any and not any(_search(pattern, text) for pattern in regex_any):
        failures.append(f"正規表現のいずれも不一致: {regex_any}")
    for pattern in expect.get("exclude_regex", []):
        if _search(pattern, text) is not None:
            failures.append(f"禁止正規表現に一致: {pattern}")
    return failures


def carry_strings(previous, specs):
    required = []
    failures = []
    for spec in specs or []:
        flags = re.M | (re.I if spec.get("ignore_case") else 0)
        match = re.search(spec["regex"], previous, flags)
        if not match:
            failures.append(f"carry 不一致: {spec['regex']}")
            continue
        value = match.group(spec.get("group", 0)).strip()
        limit = spec.get("max_len", 120)
        if len(value) > limit:
            value = value[:limit].strip()
        if not value:
            failures.append(f"carry が空: {spec['regex']}")
            continue
        required.append(value)
    return required, failures


def strip_think(content):
    return re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()


def chat(base_url, messages, temperature, max_tokens, seed):
    url = base_url.rstrip("/") + "/v1/chat/completions"
    body = json.dumps({
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.95,
        "top_k": 20,
        "max_tokens": max_tokens,
        "seed": seed,
    }).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=1800) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(2)
                continue
            raise RuntimeError(f"推論 API に接続できません: {exc}") from exc
    raise RuntimeError(str(last_error))


def model_name(base_url):
    url = base_url.rstrip("/") + "/v1/models"
    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.load(response)
    data = payload.get("data") or payload.get("models") or []
    if not data:
        return "unknown"
    item = data[0]
    return item.get("id") or item.get("model") or item.get("name") or "unknown"


def quant_slug(name):
    match = re.search(r"Qwen-AgentWorld-35B-A3B-(.+)\.gguf", name)
    if match:
        return match.group(1)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80]


def preview(text, limit=1200):
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...（{len(text)} 文字中 {limit} 文字を表示）"


def run_scenario(scenario, base_url, seed=1):
    system = resolve_system(scenario)
    messages = [{"role": "system", "content": system}]
    temperature = scenario.get("temperature", 0.6)
    max_tokens = scenario.get("max_tokens", 8192)
    model = model_name(base_url)
    started = datetime.now()
    turns = []
    previous = ""
    partial_path = RESULTS / f"{scenario['id']}.partial.json"
    print(f"\n######## {scenario['id']}  model={model}  T={temperature} seed={seed}")
    sys.stdout.flush()

    for index, turn in enumerate(scenario["turns"], 1):
        record = {
            "n": index,
            "name": turn.get("name", f"turn-{index}"),
            "passed": False,
            "failures": [],
        }
        action = turn.get("action")
        if turn.get("url_from_previous"):
            url = first_url(previous)
            if not url:
                record["failures"].append("前ターンから URL を取れなかった")
                record["skipped"] = True
                turns.append(record)
                _print_turn(record, None)
                _write_partial(partial_path, scenario, model, temperature, seed, started, turns)
                continue
            action = subst_url(action, url)
            turn = dict(turn)
            turn["action"] = action
            record["url"] = url
        extra = []
        if turn.get("carry_include"):
            carried, carry_failures = carry_strings(previous, turn["carry_include"])
            record["failures"].extend(carry_failures)
            extra = carried
            record["carry"] = carried
        try:
            action_text, action_lang = encode_action(scenario, turn)
        except Exception as exc:
            record["failures"].append(f"action 組み立て失敗: {exc}")
            turns.append(record)
            _print_turn(record, None)
            _write_partial(partial_path, scenario, model, temperature, seed, started, turns)
            continue
        user = build_user(scenario, turn, index, action_text, action_lang)
        record["user_preview"] = user[:500]
        messages.append({"role": "user", "content": user})
        t0 = time.time()
        try:
            response = chat(base_url, messages, temperature, max_tokens, seed)
        except Exception as exc:
            record["failures"].append(str(exc))
            record["seconds"] = round(time.time() - t0, 1)
            turns.append(record)
            _print_turn(record, None)
            _write_partial(partial_path, scenario, model, temperature, seed, started, turns)
            break
        seconds = time.time() - t0
        choice = response["choices"][0]
        message = choice["message"]
        raw = message.get("content") or ""
        thinking = message.get("reasoning_content") or ""
        content = strip_think(raw)
        usage = response.get("usage") or {}
        completion = usage.get("completion_tokens") or 0
        observation = observable(content)
        expect = turn.get("expect") or {}
        failures = evaluate(observation, expect, extra_include=extra)
        record.update({
            "failures": record["failures"] + failures,
            "seconds": round(seconds, 1),
            "completion_tokens": completion,
            "prompt_tokens": usage.get("prompt_tokens"),
            "tokens_per_sec": round(completion / seconds, 1) if seconds else 0,
            "thinking_chars": len(thinking),
            "finish_reason": choice.get("finish_reason"),
            "observation": observation[:50000],
        })
        if record["finish_reason"] == "length":
            record["failures"].append("max_tokens で打ち切り")
        record["passed"] = not record["failures"]
        turns.append(record)
        previous = observation
        messages.append({"role": "assistant", "content": content})
        _print_turn(record, observation)
        _write_partial(partial_path, scenario, model, temperature, seed, started, turns)

    passed = sum(1 for item in turns if item["passed"])
    failed = [item["n"] for item in turns if not item["passed"]]
    summary = {
        "id": scenario["id"],
        "description": scenario.get("description", ""),
        "model": model,
        "quant": quant_slug(model),
        "temperature": temperature,
        "seed": seed,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "total": len(turns),
        "first_failure": failed[0] if failed else None,
        "failed_turns": failed,
        "turns": turns,
    }
    paths = write_result(summary)
    partial_path.unlink(missing_ok=True)
    print(f"---- {summary['id']}: {passed}/{len(turns)}  最初の失敗={summary['first_failure']}  -> {paths[0].name}")
    sys.stdout.flush()
    return summary


def _write_partial(path, scenario, model, temperature, seed, started, turns):
    path.parent.mkdir(exist_ok=True)
    failed = [item["n"] for item in turns if not item["passed"]]
    payload = {
        "id": scenario["id"],
        "model": model,
        "quant": quant_slug(model),
        "temperature": temperature,
        "seed": seed,
        "started": started.isoformat(timespec="seconds"),
        "passed": sum(1 for item in turns if item["passed"]),
        "total_so_far": len(turns),
        "planned": len(scenario["turns"]),
        "first_failure": failed[0] if failed else None,
        "turns": turns,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _print_turn(record, observation):
    mark = "PASS" if record["passed"] else "FAIL"
    timing = ""
    if "seconds" in record:
        timing = (
            f"  {record['seconds']}秒"
            f"  {record.get('completion_tokens', 0)} tok"
            f"  {record.get('tokens_per_sec', 0)} tok/s"
            f"  思考{record.get('thinking_chars', 0)}文字"
        )
    print(f"\n===== Turn {record['n']}: {record['name']}  {mark}{timing}")
    if record["failures"]:
        for item in record["failures"]:
            print(f"  ! {item}")
    if observation:
        print(preview(observation))
    sys.stdout.flush()


def write_result(summary):
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    stem = f"{summary['id']}_{stamp}_{summary['quant']}"
    json_path = RESULTS / f"{stem}.json"
    txt_path = RESULTS / f"{stem}.txt"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = [
        f"# {summary['id']}",
        summary["description"],
        f"model: {summary['model']}",
        f"temperature: {summary['temperature']}  seed: {summary['seed']}",
        f"score: {summary['passed']}/{summary['total']}  first_failure: {summary['first_failure']}",
        "",
    ]
    for turn in summary["turns"]:
        mark = "PASS" if turn["passed"] else "FAIL"
        lines.append(f"===== Turn {turn['n']}: {turn['name']}  {mark} =====")
        if "seconds" in turn:
            lines.append(
                f"[{turn['seconds']}秒, 生成{turn.get('completion_tokens', 0)}トークン, "
                f"{turn.get('tokens_per_sec', 0)} tok/s, 思考{turn.get('thinking_chars', 0)}文字, "
                f"prompt {turn.get('prompt_tokens')} tok, finish={turn.get('finish_reason')}]"
            )
        for item in turn["failures"]:
            lines.append(f"! {item}")
        if turn.get("observation"):
            lines.append(turn["observation"])
        lines.append("")
    txt_path.write_text("\n".join(lines))
    return txt_path, json_path


def run_named(names, base_url, seed=1):
    scenarios, suites = load_catalog()
    selected = []
    for name in names:
        if name in suites:
            selected.extend(suites[name])
        elif name in scenarios:
            selected.append(name)
        else:
            raise SystemExit(f"未知のシナリオ: {name}")
    summaries = []
    for name in selected:
        summaries.append(run_scenario(scenarios[name], base_url, seed=seed))
    if len(summaries) > 1:
        RESULTS.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        rollup_path = RESULTS / f"suite_{stamp}.json"
        rollup = {
            "model": summaries[0]["model"],
            "quant": summaries[0]["quant"],
            "scenarios": [
                {
                    "id": item["id"],
                    "passed": item["passed"],
                    "total": item["total"],
                    "first_failure": item["first_failure"],
                    "failed_turns": item["failed_turns"],
                }
                for item in summaries
            ],
        }
        rollup_path.write_text(json.dumps(rollup, ensure_ascii=False, indent=2) + "\n")
        print(f"\n==== suite -> {rollup_path.name}")
        for item in rollup["scenarios"]:
            print(f"  {item['id']}: {item['passed']}/{item['total']}  first={item['first_failure']}")
    return summaries
