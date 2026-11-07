"""シナリオを実行する。

使い方:
  python3 scripts/run_scenario.py terminal_short
  python3 scripts/run_scenario.py main
  AGENTWORLD_URL=http://127.0.0.1:8080 python3 scripts/run_scenario.py quant_probe
"""
import argparse
import os

from scenario_runner import load_catalog, run_named


def main():
    scenarios, suites = load_catalog()
    parser = argparse.ArgumentParser(description="言語世界モデルのシナリオを採点する")
    parser.add_argument("names", nargs="*", help="シナリオ名または suite 名（main / quant）")
    parser.add_argument("--list", action="store_true", help="シナリオ一覧を出す")
    parser.add_argument("--url", default=os.environ.get("AGENTWORLD_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.list or not args.names:
        print("suites:", ", ".join(suites))
        for key, scenario in scenarios.items():
            print(f"  {key:20} {len(scenario['turns']):3} turns  {scenario.get('description', '')}")
        if not args.names:
            return
    run_named(args.names, args.url, seed=args.seed)


if __name__ == "__main__":
    main()
