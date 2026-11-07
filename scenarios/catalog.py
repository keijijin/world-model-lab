"""検証シナリオ。

採点はモデル出力に対する文字列オラクルである。ターミナルの数値は Linux の
bash と同じ結果（`echo` の末尾改行、パイプ先の `wc` はファイル名を出さない）
に合わせてある。UI 領域は AgentWorldBench と同様、毎ターン正解の Current State
を渡す。ターミナルとツール領域は 1 ターン目以降、状態をプロンプトに書き戻さない。
"""


def _expect(**kwargs):
    return {key: value for key, value in kwargs.items() if value}


def term(name, command, **kwargs):
    return {"name": name, "command": command, "expect": _expect(**kwargs)}


def tool(name, action, **kwargs):
    turn = {"name": name, "action": action}
    carry = kwargs.pop("carry_include", None)
    url_from_previous = kwargs.pop("url_from_previous", False)
    expect = _expect(**kwargs)
    if expect:
        turn["expect"] = expect
    if carry:
        turn["carry_include"] = carry
    if url_from_previous:
        turn["url_from_previous"] = True
    return turn


def ui(name, action, state, **kwargs):
    return {
        "name": name,
        "action": action,
        "state": state,
        "expect": _expect(**kwargs),
    }


HOME = """### Page
- Page URL: http://lab.example/
- Page Title: Lab Home
### Snapshot
```yaml
- generic [ref=e1]:
  - heading "Lab Home" [level=1] [ref=e2]
  - textbox "Name" [ref=e5]
  - link "Docs" [ref=e3] [cursor=pointer]:
    - /url: http://lab.example/docs
```"""

HOME_KEPLER = HOME.replace(
    'textbox "Name" [ref=e5]',
    'textbox "Name" [ref=e5]: Kepler',
)

DOCS = """### Page
- Page URL: http://lab.example/docs
- Page Title: Documentation
### Snapshot
```yaml
- generic [ref=e1]:
  - heading "Documentation" [level=1] [ref=e2]
  - link "Home" [ref=e3] [cursor=pointer]:
    - /url: http://lab.example/
  - paragraph [ref=e4]: Notes about the lab.
```"""

ANDROID_LIST = """\
[  0] | android.widget.TextView | text="Notes" | bounds=[40,100][500,200]
[  1] | android.widget.TextView | text="Empty" | bounds=[40,260][800,360]
[  2] | android.widget.Button | text="New note" | bounds=[760,2000][1000,2160] | clickable"""

ANDROID_EDITOR = """\
[  0] | android.widget.EditText | text="" hint="Title" | bounds=[40,200][1000,320] | editable
[  1] | android.widget.Button | text="Save" | bounds=[800,400][1000,520] | clickable"""

ANDROID_EDITOR_FILLED = ANDROID_EDITOR.replace('text="" hint="Title"', 'text="Kepler note" hint="Title"')

ANDROID_LIST_SAVED = """\
[  0] | android.widget.TextView | text="Notes" | bounds=[40,100][500,200]
[  1] | android.widget.TextView | text="Kepler note" | bounds=[40,260][800,360] | clickable
[  2] | android.widget.Button | text="New note" | bounds=[760,2000][1000,2160] | clickable"""


def sheet(a1, b1):
    return (
        "tag\tname\ttext\tclass\tdescription\tposition (top-left x&y)\tsize (w&h)\n"
        f"label\tA1\t{a1}\tcell\t\t(120, 240)\t(80, 24)\n"
        f"label\tB1\t{b1}\tcell\t\t(220, 240)\t(80, 24)\n"
        "push-button\tSave\tSave\tbutton\t\t(120, 400)\t(80, 30)"
    )


GONE = ["No such file", "not found", "does not exist", "File not found"]
NUM = r"(?<![0-9]){}(?![0-9])"

SCENARIOS = {
    "terminal_short": {
        "id": "terminal_short",
        "description": "README の6ターン（作成、サイズ、削除）を機械採点する",
        "style": "terminal",
        "system_prompt": "prompts/terminal/system_prompt.txt",
        "initial_state": "root@demo:/app#",
        "max_tokens": 8192,
        "turns": [
            term("mkdir", "mkdir project && cd project", include=["root@demo:/app/project#"]),
            term(
                "write",
                "echo 'hello world' > greeting.txt",
                include=["root@demo:/app/project#"],
                exclude=["No such file"],
            ),
            term(
                "ls",
                "ls -la",
                include=["greeting.txt"],
                regex=[r"(?m)^.*\b12\b.*greeting\.txt"],
            ),
            term("wc", "cat greeting.txt | wc -c", regex=[r"(?m)^\s*12\s*$"]),
            term(
                "rm",
                "rm greeting.txt",
                include=["root@demo:/app/project#"],
                exclude=["No such file"],
            ),
            term(
                "cat gone",
                "cat greeting.txt",
                include_any=GONE,
                exclude=["hello world"],
            ),
        ],
    },
    "domain_web": {
        "id": "domain_web",
        "description": "フォーム入力、リンク遷移、別 URL への再読込",
        "style": "ui",
        "action_lang": "text",
        "system_prompt": "prompts/web/system_prompt.txt",
        "max_tokens": 8192,
        "turns": [
            ui(
                "fill",
                'browser_fill_form(fields=[{"name": "Name", "ref": "e5", "type": "textbox", "value": "Kepler"}])',
                HOME,
                include=['heading "Lab Home"', "### Page", "Kepler"],
                regex=[r"(?m)^- Page URL: http://lab\.example/\s*$"],
                regex_any=[
                    r'textbox "Name" \[ref=e5\]: Kepler',
                    r'textbox "Name" \[ref=e5\] \[value="Kepler"\]',
                ],
            ),
            ui(
                "open docs",
                'browser_click(element="Docs", ref="e3")',
                HOME_KEPLER,
                include=["### Page"],
                regex=[r"(?m)^- Page URL: http://lab\.example/docs\s*$"],
                exclude_regex=[r"(?m)^- Page URL: http://lab\.example/\s*$"],
            ),
            ui(
                "navigate home",
                'browser_navigate(url="http://lab.example/")',
                DOCS,
                include=['heading "Lab Home"', 'textbox "Name" [ref=e5]'],
                exclude=["Kepler", 'heading "Documentation"'],
                regex=[r"(?m)^- Page URL: http://lab\.example/\s*$"],
            ),
            ui(
                "fill again",
                'browser_fill_form(fields=[{"name": "Name", "ref": "e5", "type": "textbox", "value": "Galileo"}])',
                HOME,
                include=['textbox "Name" [ref=e5]: Galileo'],
                exclude=["Kepler"],
                regex=[r"(?m)^- Page URL: http://lab\.example/\s*$"],
            ),
        ],
    },
    "domain_android": {
        "id": "domain_android",
        "description": "ノートの新規作成、入力、保存、開き直し",
        "style": "ui",
        "action_lang": "json",
        "system_prompt": "prompts/android/system_prompt.txt",
        "max_tokens": 16384,
        "turns": [
            ui(
                "new",
                {"action_type": "click", "index": 2},
                ANDROID_LIST,
                include=["android.widget.EditText"],
                exclude=['text="Empty"'],
            ),
            ui(
                "type",
                {"action_type": "input_text", "text": "Kepler note", "index": 0},
                ANDROID_EDITOR,
                include=['text="Kepler note"'],
            ),
            ui(
                "save",
                {"action_type": "click", "index": 1},
                ANDROID_EDITOR_FILLED,
                include=['text="Kepler note"', 'text="Notes"'],
                exclude=['hint="Title"'],
            ),
            ui(
                "reopen",
                {"action_type": "click", "index": 1},
                ANDROID_LIST_SAVED,
                include=["android.widget.EditText", 'text="Kepler note"'],
            ),
        ],
    },
    "domain_os": {
        "id": "domain_os",
        "description": "表計算のセルを更新し、隣のセルが残るか見る",
        "style": "ui",
        "action_lang": "text",
        "system_prompt": "prompts/os/system_prompt.txt",
        "task": "Edit the open spreadsheet.",
        "max_tokens": 8192,
        "turns": [
            ui(
                "set A1",
                "CalcTools.set_cell_value(cell='A1', value='42')",
                sheet("", ""),
                include=["A1", "position (top-left x&y)"],
                regex=[NUM.format(42)],
                exclude_regex=[NUM.format(7)],
            ),
            ui(
                "set B1",
                "CalcTools.set_cell_value(cell='B1', value='7')",
                sheet("42", ""),
                include=["A1", "B1"],
                regex=[NUM.format(42), NUM.format(7)],
            ),
            ui(
                "overwrite A1",
                "CalcTools.set_cell_value(cell='A1', value='100')",
                sheet("42", "7"),
                include=["A1", "B1"],
                regex=[NUM.format(100), NUM.format(7)],
                exclude_regex=[NUM.format(42)],
            ),
        ],
    },
    "domain_mcp": {
        "id": "domain_mcp",
        "description": "ファイルの作成、移動、削除後の参照",
        "style": "tool",
        "system_prompt": "prompts/mcp/system_prompt.txt",
        "system_subs": {
            "{tool_definitions}": {"file": "prompts/mcp/tool_definitions.txt"},
            "{demonstrations}": {"file": "prompts/mcp/demonstrations.txt"},
        },
        "max_tokens": 8192,
        "turns": [
            tool(
                "write a",
                {"name": "write_file", "arguments": {"path": "/notes/a.txt", "content": "alpha-stone"}},
                include=["/notes/a.txt"],
                include_any=["Successfully wrote", "alpha-stone"],
                exclude=["No such file"],
            ),
            tool(
                "read a",
                {"name": "read_text_file", "arguments": {"path": "/notes/a.txt"}},
                include=["alpha-stone"],
            ),
            tool(
                "write b",
                {"name": "write_file", "arguments": {"path": "/notes/b.txt", "content": "beta-stone"}},
                include=["/notes/b.txt"],
                include_any=["Successfully wrote", "beta-stone"],
            ),
            tool(
                "move",
                {"name": "move_file", "arguments": {"source": "/notes/a.txt", "destination": "/notes/c.txt"}},
                include=["/notes/c.txt"],
                include_any=["Successfully moved", "moved"],
            ),
            tool(
                "read old",
                {"name": "read_text_file", "arguments": {"path": "/notes/a.txt"}},
                include_any=GONE,
                exclude=["alpha-stone"],
            ),
            tool(
                "read new",
                {"name": "read_text_file", "arguments": {"path": "/notes/c.txt"}},
                include=["alpha-stone"],
                exclude=["beta-stone"],
            ),
            tool(
                "list",
                {"name": "list_directory", "arguments": {"path": "/notes"}},
                include=["b.txt", "c.txt"],
                exclude=["a.txt"],
            ),
        ],
    },
    "domain_search": {
        "id": "domain_search",
        "description": "記憶の更新と、検索結果から本文への引き写し",
        "style": "tool",
        "system_prompt": "prompts/search/system_prompt.txt",
        "system_subs": {
            "{tool_definitions}": {"file": "prompts/search/tool_definitions.txt"},
        },
        "max_tokens": 16384,
        "turns": [
            tool(
                "remember",
                {
                    "name": "dict_memory",
                    "arguments": {"operation": "add", "dict": {"comet": "halley", "year": "1986"}},
                },
                include_any=["Successfully added", "halley"],
                exclude=["Key not found"],
            ),
            tool(
                "recall mixed",
                {
                    "name": "dict_memory",
                    "arguments": {"operation": "retrieve", "key_list": ["comet", "missing"]},
                },
                include=["halley", "Key not found"],
            ),
            tool(
                "update",
                {
                    "name": "dict_memory",
                    "arguments": {"operation": "update", "dict": {"comet": "neowise"}},
                },
                include_any=["Successfully updated", "updated", "neowise"],
            ),
            tool(
                "recall new",
                {
                    "name": "dict_memory",
                    "arguments": {"operation": "retrieve", "key_list": ["comet"]},
                },
                include=["neowise"],
                exclude=["halley"],
            ),
            tool(
                "forget",
                {
                    "name": "dict_memory",
                    "arguments": {"operation": "remove", "key_list": ["comet"]},
                },
                include_any=["Successfully removed", "removed"],
            ),
            tool(
                "recall gone",
                {
                    "name": "dict_memory",
                    "arguments": {"operation": "retrieve", "key_list": ["comet"]},
                },
                include=["Key not found"],
                exclude=["neowise", "halley"],
            ),
            tool(
                "search light",
                {
                    "name": "web_search",
                    "arguments": {"queries": ["speed of light in vacuum exact value metres per second"]},
                },
                include_any=["299792458", "299,792,458"],
                regex=[r"\[1\] https://"],
            ),
            tool(
                "extract light",
                {
                    "name": "web_extractor",
                    "arguments": {
                        "urls": ["{url}"],
                        "goal": "Quote the sentence that states the exact integer speed of light in vacuum, in metres per second.",
                    },
                },
                url_from_previous=True,
                carry_include=[{
                    "regex": r"(?i)Title:\s*(.+?)(?:\s+-\s+.*)?$",
                    "group": 1,
                    "max_len": 80,
                    "ignore_case": True,
                }],
                include_any=["299792458", "299,792,458"],
            ),
        ],
    },
    "domain_swe": {
        "id": "domain_swe",
        "description": "ファイル作成、実行、編集後の再実行、削除",
        "style": "tool",
        "arguments_as_string": True,
        "system_prompt": "prompts/swe/system_prompt.txt",
        "system_subs": {
            "{tool_definitions}": {"file": "prompts/swe/tool_definitions.txt"},
            "{demonstrations}": {"file": "prompts/swe/demonstrations.txt"},
        },
        "max_tokens": 8192,
        "turns": [
            tool(
                "write",
                {
                    "name": "Write",
                    "arguments": {
                        "file_path": "/app/src/main.py",
                        "content": 'TOKEN = "swe-token-9"\nprint(TOKEN)\n',
                    },
                },
                include=["/app/src/main.py"],
                include_any=["File created successfully", "created", "Wrote"],
            ),
            tool(
                "read",
                {"name": "Read", "arguments": {"file_path": "/app/src/main.py"}},
                include=["swe-token-9"],
            ),
            tool(
                "run",
                {"name": "Bash", "arguments": {"command": "python3 /app/src/main.py"}},
                include=["swe-token-9"],
            ),
            tool(
                "edit",
                {
                    "name": "Edit",
                    "arguments": {
                        "file_path": "/app/src/main.py",
                        "old_string": "swe-token-9",
                        "new_string": "swe-token-3",
                    },
                },
                include_any=["updated", "edited", "success", "swe-token-3"],
            ),
            tool(
                "read edited",
                {"name": "Read", "arguments": {"file_path": "/app/src/main.py"}},
                include=["swe-token-3"],
                exclude=["swe-token-9"],
            ),
            tool(
                "run edited",
                {"name": "Bash", "arguments": {"command": "python3 /app/src/main.py"}},
                include=["swe-token-3"],
                exclude=["swe-token-9"],
            ),
            tool(
                "delete",
                {"name": "Bash", "arguments": {"command": "rm /app/src/main.py"}},
                allow_empty=True,
                exclude=["No such file", "File not found"],
            ),
            tool(
                "read deleted",
                {"name": "Read", "arguments": {"file_path": "/app/src/main.py"}},
                include_any=GONE,
                exclude=["swe-token-3", "swe-token-9"],
            ),
        ],
    },
    "tricky_terminal": {
        "id": "tricky_terminal",
        "description": "mv、パイプ、引用符、一時的な変数代入、サブシェル",
        "style": "terminal",
        "system_prompt": "prompts/terminal/system_prompt.txt",
        "initial_state": "root@demo:/app#",
        "max_tokens": 8192,
        "turns": [
            term("mkdir", "mkdir box && cd box", include=["root@demo:/app/box#"]),
            term(
                "printf",
                "printf 'one\\ntwo\\nthree\\n' > nums.txt",
                include=["root@demo:/app/box#"],
                exclude=["No such file"],
            ),
            term("wc lines", "cat nums.txt | wc -l", regex=[r"(?m)^\s*3\s*$"]),
            term("wc bytes", "cat nums.txt | wc -c", regex=[r"(?m)^\s*14\s*$"]),
            term(
                "mv rename",
                "echo hello > a.txt && mv a.txt b.txt",
                include=["root@demo:/app/box#"],
                exclude=["No such file"],
            ),
            term("cat old name", "cat a.txt", include_any=GONE, exclude=["hello"]),
            term("cat new name", "cat b.txt", include=["hello"]),
            term("mv into missing dir", "mv b.txt sub/b.txt", include_any=GONE),
            term("still there", "cat b.txt", include=["hello"]),
            term(
                "mv into dir",
                "mkdir sub && mv b.txt sub/renamed.txt",
                include=["root@demo:/app/box#"],
                exclude=["No such file"],
            ),
            term("cat moved", "cat sub/renamed.txt", include=["hello"]),
            term("cat source gone", "cat b.txt", include_any=GONE, exclude=["hello"]),
            term("export", "export FOO=apple", include=["root@demo:/app/box#"]),
            term("expand", 'echo "$FOO"', regex=[r"(?m)^apple$"]),
            term(
                "single quotes",
                "echo '$FOO'",
                regex=[r"(?m)^\$FOO$"],
                exclude_regex=[r"(?m)^apple$"],
            ),
            term(
                "prefix assign",
                'FOO=banana echo "$FOO"',
                regex=[r"(?m)^apple$"],
                exclude_regex=[r"(?m)^banana$"],
            ),
            term(
                "prefix does not persist",
                'echo "$FOO"',
                regex=[r"(?m)^apple$"],
                exclude_regex=[r"(?m)^banana$"],
            ),
            term("braces", 'echo "x${FOO}y"', regex=[r"(?m)^xappley$"]),
            term("pipe tr", 'echo "$FOO" | tr a-z A-Z', regex=[r"(?m)^APPLE$"]),
            term(
                "pipe missing",
                "cat missing.txt | wc -l",
                include_any=GONE,
                regex=[r"(?m)^\s*0\s*$"],
            ),
            term(
                "stage overwrite",
                "echo NEW > new.txt && echo OLD > old.txt && mv new.txt old.txt",
                include=["root@demo:/app/box#"],
            ),
            term(
                "cat overwritten",
                "cat old.txt",
                regex=[r"(?m)^NEW$"],
                exclude_regex=[r"(?m)^OLD$"],
            ),
            term("cat moved-away", "cat new.txt", include_any=GONE, exclude=["NEW"]),
            term(
                "subshell",
                "(cd sub && pwd) && pwd",
                regex=[r"(?m)^/app/box/sub$", r"(?m)^/app/box$"],
            ),
        ],
    },
    "long_terminal": {
        "id": "long_terminal",
        "description": "33ターンでファイルと作業ディレクトリを追跡し、最初に崩れる地点を記録する",
        "style": "terminal",
        "system_prompt": "prompts/terminal/system_prompt.txt",
        "initial_state": "root@demo:/app#",
        "max_tokens": 8192,
        "turns": [
            term(
                "mkdir",
                "mkdir -p lab/src lab/data && cd lab",
                include=["root@demo:/app/lab#"],
                exclude=["root@demo:/app/lab/src#", "root@demo:/app/lab/data#", "No such file"],
            ),
            term("write alpha", "echo TOKEN_ALPHA > src/a.txt", include=["root@demo:/app/lab#"], exclude=["No such file"]),
            term("write beta", "printf 'TOKEN_BETA\\nTOKEN_BETA\\n' > src/b.txt", include=["root@demo:/app/lab#"]),
            term("write gamma", "echo TOKEN_GAMMA > data/c.txt", include=["root@demo:/app/lab#"]),
            term("write delta", "echo TOKEN_DELTA > data/d.txt", include=["root@demo:/app/lab#"]),
            term("ls src", "ls src", include=["a.txt", "b.txt"], exclude=["c.txt", "d.txt"]),
            term(
                "wc alpha",
                "wc -c src/a.txt",
                regex_any=[r"(?m)^\s*12\s*$", r"(?m)^\s*12\s+src/a\.txt\s*$"],
            ),
            term(
                "wc beta lines",
                "wc -l src/b.txt",
                regex_any=[r"(?m)^\s*2\s*$", r"(?m)^\s*2\s+src/b\.txt\s*$"],
            ),
            term("cat alpha", "cat src/a.txt", include=["TOKEN_ALPHA"], exclude=["TOKEN_BETA"]),
            term("cat gamma delta", "cat data/c.txt data/d.txt", include=["TOKEN_GAMMA", "TOKEN_DELTA"]),
            term("cd src", "cd src", include=["root@demo:/app/lab/src#"]),
            term("cat alpha relative", "cat a.txt", include=["TOKEN_ALPHA"]),
            term("cd data", "cd ../data", include=["root@demo:/app/lab/data#"]),
            term("cat gamma relative", "cat c.txt", include=["TOKEN_GAMMA"]),
            term(
                "cd lab",
                "cd /app/lab",
                # コマンドエコー行には移動前のプロンプトが残る。最終行だけを見る。
                regex=[r"(?m)^root@demo:/app/lab#$"],
                exclude_regex=[r"(?m)^root@demo:/app/lab/(data|src|nested)#$"],
            ),
            term("rename", "mv src/a.txt src/a_renamed.txt", include=["root@demo:/app/lab#"], exclude=["No such file"]),
            term("cat old alpha", "cat src/a.txt", include_any=GONE, exclude=["TOKEN_ALPHA"]),
            term("cat renamed", "cat src/a_renamed.txt", include=["TOKEN_ALPHA"], exclude=["TOKEN_EPSILON"]),
            term("append", "echo TOKEN_EPSILON >> src/a_renamed.txt", include=["root@demo:/app/lab#"]),
            term(
                "cat appended",
                "cat src/a_renamed.txt",
                include=["TOKEN_ALPHA", "TOKEN_EPSILON"],
                regex=[r"TOKEN_ALPHA[\s\S]{0,40}TOKEN_EPSILON"],
            ),
            term("rm delta", "rm data/d.txt", include=["root@demo:/app/lab#"], exclude=["No such file"]),
            term("cat delta", "cat data/d.txt", include_any=GONE, exclude=["TOKEN_DELTA"]),
            term("gamma remains", "cat data/c.txt", include=["TOKEN_GAMMA"], exclude=["TOKEN_DELTA"]),
            term("write zeta", "mkdir -p nested/deep && echo TOKEN_ZETA > nested/deep/note.txt", include=["root@demo:/app/lab#"]),
            term("find note", "find . -name note.txt", include=["nested/deep/note.txt"]),
            term("rm nested", "rm -r nested", include=["root@demo:/app/lab#"], exclude=["No such file"]),
            term("cat note", "cat nested/deep/note.txt", include_any=GONE, exclude=["TOKEN_ZETA"]),
            term("beta remains", "cat src/b.txt", include=["TOKEN_BETA"], exclude=["TOKEN_ALPHA"]),
            term(
                "renamed remains",
                "cat src/a_renamed.txt",
                include=["TOKEN_ALPHA", "TOKEN_EPSILON"],
            ),
            term("ls data", "ls data", include=["c.txt"], exclude=["d.txt"]),
            term("overwrite gamma", "echo TOKEN_ETA > data/c.txt", include=["root@demo:/app/lab#"]),
            term("cat eta", "cat data/c.txt", include=["TOKEN_ETA"], exclude=["TOKEN_GAMMA"]),
            term(
                "pwd",
                "pwd",
                regex=[r"(?m)^/app/lab$"],
                exclude_regex=[r"(?m)^/app/lab/(src|data|nested)$"],
            ),
        ],
    },
    "quant_probe": {
        "id": "quant_probe",
        "description": "量子化比較用の短いターミナル（バイト数、mv、引用符、前置代入）",
        "style": "terminal",
        "system_prompt": "prompts/terminal/system_prompt.txt",
        "initial_state": "root@demo:/app#",
        "max_tokens": 8192,
        "turns": [
            term("mkdir", "mkdir project && cd project", include=["root@demo:/app/project#"]),
            term("write", "echo 'hello world' > greeting.txt", include=["root@demo:/app/project#"]),
            term("wc", "cat greeting.txt | wc -c", regex=[r"(?m)^\s*12\s*$"]),
            term("mv", "mv greeting.txt hello.txt", include=["root@demo:/app/project#"], exclude=["No such file"]),
            term("cat old", "cat greeting.txt", include_any=GONE, exclude=["hello world"]),
            term("cat new", "cat hello.txt", include=["hello world"]),
            term("export", "export NAME=ada", include=["root@demo:/app/project#"]),
            term("expand", 'echo "$NAME"', regex=[r"(?m)^ada$"]),
            term(
                "literal",
                "echo '$NAME'",
                regex=[r"(?m)^\$NAME$"],
                exclude_regex=[r"(?m)^ada$"],
            ),
            term(
                "prefix",
                'NAME=bob echo "$NAME"',
                regex=[r"(?m)^ada$"],
                exclude_regex=[r"(?m)^bob$"],
            ),
        ],
    },
}

SUITES = {
    "main": [
        "terminal_short",
        "domain_web",
        "domain_android",
        "domain_mcp",
        "domain_search",
        "domain_swe",
        "domain_os",
        "tricky_terminal",
        "long_terminal",
    ],
    "quant": ["quant_probe"],
}
