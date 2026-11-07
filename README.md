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

## 今後の検証予定

- [ ] 他の6領域（Web、Android、MCP、Search、SWE、OS）を試す
- [ ] 長いシナリオ（数十ターン）で、状態の一貫性がどこで崩れるか調べる
- [ ] 意図的に紛らわしい操作（`mv`、パイプ、環境変数など）で正確さを測る
- [ ] 量子化の度合い（IQ4_XS、Q5、Q8）による精度と速度の違いを比べる

## ディレクトリ構成

```
.
├── README.md
├── prompts/terminal/system_prompt.txt   # Qwen公式のターミナル用システムプロンプト
├── scripts/
│   ├── download_model.sh                # GGUFモデルのダウンロード
│   ├── start_server.sh                  # llama-server の起動
│   └── test_terminal.py                 # ターミナル世界モデルのテスト
├── results/                             # 検証結果
└── models/                              # モデル本体（git管理外）
```

## クレジット・ライセンス

- `prompts/` 以下のプロンプトは [QwenLM/Qwen-AgentWorld](https://github.com/QwenLM/Qwen-AgentWorld) から取得したもので、Apache License 2.0 に従います。
- モデル：[Qwen/Qwen-AgentWorld-35B-A3B](https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B)（Apache License 2.0）
- 論文：Zuo et al., *Qwen-AgentWorld: Language World Models for General Agents*, arXiv:2606.24597, 2026.
