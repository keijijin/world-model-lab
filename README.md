# World Model Lab

言語世界モデル（Language World Model）**Qwen-AgentWorld** を、Apple Silicon の Mac 上でローカルに動かして検証するプロジェクトです。

## 背景：世界モデルとは

世界モデルとは、「ある状態で、ある行動をとると、次に何が起こるか」を予測するモデルです。

```
次の状態 s(t+1) = f( 今の状態 s(t), 行動 a(t) )
```

通常の言語モデルが「人間なら次に何を書くか」を予測するのに対し、言語世界モデルは**「行動したら環境（ターミナル、Web、OS など）がどう応答するか」**を予測します。学習には、（状態, 行動, 次の状態）という実際の操作記録が使われます。

[Qwen-AgentWorld](https://arxiv.org/abs/2606.24597)（Alibaba Qwen、2026年6月）は、7つの領域（MCP、Search、Terminal、SWE、Android、Web、OS）を1つのモデルでシミュレーションできる言語世界モデルです。

## 検証環境

| 項目 | 内容 |
|---|---|
| マシン | Apple M3 Pro（GPU 18コア）、メモリ 36GB |
| 推論エンジン | llama.cpp `llama-server`（version 8680） |
| モデル | [unsloth/Qwen-AgentWorld-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen-AgentWorld-35B-A3B-GGUF) の `UD-Q4_K_M`（22.1GB） |
| アーキテクチャ | `qwen35moe`（総パラメータ 35B、実際に動くのは 3B） |
| 文脈長 | 32,768 トークン |

## セットアップ

前提：`llama.cpp`（`brew install llama.cpp`）と Python 3 がインストールされていること。

```bash
# 1. モデルをダウンロード（約22GB、models/ に保存）
./scripts/download_model.sh

# 2. サーバーを起動（http://127.0.0.1:8080）
./scripts/start_server.sh

# 3. 別のターミナルでテストを実行
python3 scripts/test_terminal.py | tee results/my_run.txt
```

量子化の種類を変えるには、`./scripts/download_model.sh UD-IQ4_XS` のように引数で指定します。サーバー起動時も同じ引数を渡してください。

## 検証1：ターミナル環境のシミュレーション

公式のターミナル用システムプロンプト（`prompts/terminal/system_prompt.txt`）を使い、6ターンのコマンドを順に送って、状態の一貫性を確認しました。**コマンドは実際には実行しておらず、出力はすべてモデルの予測です。**

| ターン | 行動 | 予測された結果 | 判定 |
|---|---|---|---|
| 1 | `mkdir project && cd project` | プロンプトが `/app/project#` に変化 | ✅ |
| 2 | `echo 'hello world' > greeting.txt` | 出力なしでプロンプトに戻る | ✅ |
| 3 | `ls -la` | `greeting.txt` が 12 バイトで表示される | ✅ |
| 4 | `cat greeting.txt \| wc -c` | `12` | ✅（`hello world\n` は12バイト） |
| 5 | `rm greeting.txt` | 出力なしでプロンプトに戻る | ✅ |
| 6 | `cat greeting.txt` | `No such file or directory` | ✅（削除を覚えている） |

全結果：[results/terminal_2026-11-07_Q4_K_M.txt](results/terminal_2026-11-07_Q4_K_M.txt)

### 性能

| 指標 | 値 |
|---|---|
| 生成速度 | 約 23〜28 トークン/秒 |
| 1ターンあたりの時間 | 23〜68 秒 |
| 1ターンあたりの思考（`<think>`）の長さ | 1,800〜5,000 文字 |
| KV キャッシュ | 640MB（文脈 32K） |

### 考察

- **状態の追跡ができている**：ディレクトリの移動、ファイルの作成と削除、ファイルサイズといった「見えない状態」を、ターンをまたいで矛盾なく保っていました。
- **思考が長い**：出力自体は短いのに、毎回数千文字かけて「今どこにいるか」「ファイルは何バイトか」を推論しています。精度の源はこの推論だと考えられますが、強化学習のシミュレーターとして大量に回すには遅めです。
- **メモリ効率が良い**：40層のうちアテンション層は10層だけ（残りは Gated DeltaNet）なので、KV キャッシュが非常に小さくなっています。36GB の Mac でも、文脈長を大きく伸ばす余地があります。

採点付きの一式は次で実行します。温度 0.6、`seed` 1 です。数値は各シナリオ 1 回の結果です。報告書は [results/verification_report_2026-11-07.md](results/verification_report_2026-11-07.md) です。

```bash
python3 scripts/test_checks.py          # モデルを呼ばない採点器のテスト
python3 scripts/run_scenario.py main    # 下の検証 2〜4
python3 scripts/compare_quants.py --include-running
```

期待する文字列は `scenarios/catalog.py` にあります。シナリオ中のコマンドは、この Mac では実行していません。出力はモデルの予測です。

## 検証2：他の6領域

UI 領域（Web、Android、OS）は、AgentWorldBench と同じく、毎ターンこちらが書いた画面を渡しています。画面を記憶できているかではなく、その画面への1手の予測です。MCP、Search、SWE はツール結果だけを履歴に残し、画面は書き戻していません。

モデルは `UD-Q4_K_M`、生成速度は約 27〜29 トークン/秒です。

| 領域 | 結果 | どこでずれたか |
|---|---|---|
| Web | 3/4 | 空欄へ `Kepler` を入れるとき、`: Kepler` ではなく `[value="Kepler"]` と書いた。URL は `http://lab.example/` のまま。Docs への遷移、ホームへの再読込、次の `Galileo` 入力は通った |
| Android | 4/4 | `max_tokens` 8192 では、保存済みノートを開き直すターンの思考が予算を使い切り、観測が空だった。16384 にすると 12184 トークンで完了し、`Kepler note` が編集画面に残った |
| MCP | 7/7 | 作成、移動、移動元の不在、移動先の内容、一覧まで一致 |
| Search | 7/8 | 記憶の追加・更新・削除は一致。真空中の光速は `299,792,458`。抽出本文にも同じ数値と見出し `Speed of light` がある。自動採点だけ、検索タイトルの接尾辞 ` - Wikipedia` が本文に無いため落ちた |
| SWE | 8/8 | 作成、実行、編集後の再実行（`swe-token-9` から `swe-token-3`）、削除後の不在まで一致 |
| OS | 3/3 | A1 を `42` から `100` に変えても、B1 の `7` は残った |

全記録は `results/domain_*_UD-Q4_K_M.txt` と `results/suite_2026-11-07_2106.json` です。Android の再実行は `results/domain_android_2026-11-07_2122_UD-Q4_K_M.txt` です。

## 検証3：33ターンのターミナル

`long_terminal` は作業ディレクトリ、改名、追記、兄弟ファイルの削除、上書き、`find`、`rm -r` をまたいで `TOKEN_ALPHA` から `TOKEN_ETA` を追跡します。自動採点は 32/33、最初の不合格はターン15です。

ターン15の出力は次のとおりで、移動自体は正しいものでした。不合格は、コマンドエコー行に残る移動前プロンプト `root@demo:/app/lab/data#` を「残ってはいけない」と採点したためです。

```
root@demo:/app/lab/data# cd /app/lab
root@demo:/app/lab#
```

ターン16以降のプロンプトは `root@demo:/app/lab#` のままです。ターン33の `pwd` は `/app/lab` で、改名と追記をした `src/a_renamed.txt` には `TOKEN_ALPHA` と `TOKEN_EPSILON` が残っていました。この33ターンの中では、ファイルの中身と位置の追跡は崩れていません。プロンプトトークンは 3153 から 5989 まで増え、文脈 32768 には収まりました。33ターンで約 24 分です。

記録：`results/long_terminal_2026-11-07_2106_UD-Q4_K_M.txt`

## 検証4：紛らわしいシェル操作

`tricky_terminal` は 24/24 です。次はすべて、Linux の bash と同じ結果でした。

- `mv` で改名したあと、古い名前は無く、新しい名前に内容が残る
- 存在しないディレクトリへの `mv` は失敗し、元のファイルは残る
- `mv` が既存ファイルを上書きすると、残るのは移動元の内容
- `echo "$FOO"` は展開され、`echo '$FOO'` はリテラル
- `FOO=banana echo "$FOO"` は、すでに `export` された `apple` を出す。前置代入は `$FOO` の展開には効かず、次のコマンドにも残らない
- 存在しないファイルを `wc` にパイプすると、`No such file` と `0` の両方が出る
- `(cd sub && pwd) && pwd` はサブシェルの中だけ移動する

記録：`results/tricky_terminal_2026-11-07_2042_UD-Q4_K_M.txt`

## 検証5：量子化

同じ10ターン（バイト数、`mv`、引用符、前置代入）を、温度 0.6、`seed` 1 で各1回ずつ採点しました。Unsloth のファイル名では、IQ4_XS は `UD-IQ4_XS`、Q5 は `UD-Q5_K_M`、Q8 は `Q8_0` です。比較に、これまで使っていた `UD-Q4_K_M` も入れています。

| 量子化 | ファイル | サイズ | 正答 | 生成速度 | 1ターン |
|---|---|---|---|---|---|
| IQ4_XS | `UD-IQ4_XS` | 16.56 GiB | 10/10 | 30.0 tok/s | 40.8 秒 |
| Q4_K_M | `UD-Q4_K_M` | 20.61 GiB | 10/10 | 26.7 tok/s | 44.2 秒 |
| Q5 | `UD-Q5_K_M` | 24.64 GiB | 10/10 | 26.4 tok/s | 47.1 秒 |
| Q8 | `Q8_0` | 34.37 GiB | 未実行 | — | — |

この10ターンでは正答に差はありません。速度は IQ4_XS が一番速く、Q5 は Q4_K_M とほぼ同じでした。Q8 はファイルが物理メモリ 36GiB の 80% を超えるため、ロードしていません。

長いシナリオと6領域は `UD-Q4_K_M` だけです。量子化による精度差は、この短いプローブの外では測っていません。

記録：`results/quant_compare_2026-11-07_2233.txt`

## 検証項目

- [x] 他の6領域（Web、Android、MCP、Search、SWE、OS）を試す
- [x] 長いシナリオ（数十ターン）で、状態の一貫性がどこで崩れるか調べる
- [x] 意図的に紛らわしい操作（`mv`、パイプ、環境変数など）で正確さを測る
- [x] 量子化の度合い（IQ4_XS、Q5、Q8）による精度と速度の違いを比べる

## ディレクトリ構成

```
.
├── README.md
├── prompts/                  # 7領域の公式システムプロンプト。MCP と SWE のツール定義は追加分
├── scenarios/catalog.py      # 検証シナリオと期待する文字列
├── scripts/
│   ├── download_model.sh
│   ├── start_server.sh
│   ├── test_terminal.py      # 初期の6ターン表示
│   ├── run_scenario.py       # 採点付き実行
│   ├── scenario_runner.py
│   ├── compare_quants.py     # IQ4_XS / Q5 / Q8 の比較
│   └── test_checks.py
├── results/
└── models/                   # モデル本体（git管理外）
```

## クレジット・ライセンス

- `prompts/` 以下のプロンプトは [QwenLM/Qwen-AgentWorld](https://github.com/QwenLM/Qwen-AgentWorld) から取得したもので、Apache License 2.0 に従います。
- モデル：[Qwen/Qwen-AgentWorld-35B-A3B](https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B)（Apache License 2.0）
- 論文：Zuo et al., *Qwen-AgentWorld: Language World Models for General Agents*, arXiv:2606.24597, 2026.
