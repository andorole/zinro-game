"""知識ファイル(knowledge/)から、ボットのシステムプロンプトを組み立てる。

構成: 指示(bot_prompt.md) + 型の一覧と語彙(discussion_style.md の表) + 発言例(examples.jsonl)。
発言例は、型ごとに B・A(tier 1・2)から選び、役職に合うものを優先する。評価のときは、
再生するゲームの発言例を除ける(exclude_games)。生ログは使わない(git に載っているものだけで組み立てる)。
"""
from __future__ import annotations

import re
from pathlib import Path

from zinro_learn.check import load_examples, parse_table, table_cells

CACHE = {"type": "ephemeral"}
ROLE_UNSET = "（ユーザーが指定する。村人か人狼）"
ME_UNSET = "（あなたの名前）"

# 型ごとに選ぶ発言例の数(多いほど、その型が中心)
PER_MOVE = {
    "rebut": 5, "probe": 4, "tally": 4, "stance": 3, "joke": 3, "clarify": 2, "defend": 2, "concede": 2,
    "contradiction": 2, "appeal": 2, "react": 2, "meta": 2, "banter": 2, "topic": 2, "redirect": 2, "compare": 2,
    "turnabout": 2, "quote": 2, "counter_accuse": 2, "greet": 1, "opener": 1, "lock": 2, "ultimatum": 1,
    "dilemma": 1, "distortion": 1, "preempt": 1, "misread": 1, "analogy": 1, "solicit": 1, "deescalate": 1,
}
# 相手側(tier 3)の例として見せる型。真似るのではなく、読む対象として
OPPONENT_MOVES = ("tally", "compare", "appeal", "concede", "counter_accuse", "ultimatum", "hedge", "quote", "clarify")


def read_section(text: str, heading: str) -> str:
    """`## 見出し` から次の `## ` の手前まで。"""
    m = re.search(rf"^## {re.escape(heading)}\s*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def moves_text(style: str) -> str:
    """発言の型の表を、1行ずつの一覧に直す。"""
    lines = []
    for tag, cells in parse_table(read_section(style, "発言の型")).items():
        lines.append(f"- {tag}: {cells[1]}。形: {cells[2]}")
    return "\n".join(lines)


def vocabulary_text(style: str) -> str:
    """語彙の表を「用語: 意味」の一覧に直す。"""
    lines = []
    for line in read_section(style, "語彙").splitlines():
        if not line.startswith("|"):
            continue
        cells = table_cells(line)
        if len(cells) == 2 and cells[0] not in ("用語", "---", "") and not set(cells[0]) <= {"-"}:
            lines.append(f"- {cells[0]}: {cells[1]}")
    return "\n".join(lines)


def score(ex: dict, role: str | None) -> float:
    s = {1: 2.0, 2: 1.0}.get(ex["tier"], 0.0)
    if role and ex["role"] == role:
        s += 1.0
    size = len(ex["utterance"])
    s += 1.0 if 20 <= size <= 190 else (-2.0 if size > 200 else 0.0)
    if ex.get("note"):
        s += 0.5
    return s


def pick(pool: list[dict], move: str, count: int, role: str | None, taken: set[str]) -> list[dict]:
    """その型の例を、点数の高い順に選ぶ。同じゲームからは続けて選ばない(かたよらせない)。"""
    ranked = sorted((e for e in pool if move in e["moves"] and e["id"] not in taken), key=lambda e: (-score(e, role), e["id"]))
    chosen: list[dict] = []
    per_game: dict[str, int] = {}
    for ex in ranked:
        if len(chosen) == count:
            break
        if per_game.get(ex["game"], 0) >= 1 + count // 4:
            continue
        per_game[ex["game"]] = per_game.get(ex["game"], 0) + 1
        chosen.append(ex)
    for ex in ranked:  # 足りなければ、ゲームの偏りを許して埋める
        if len(chosen) == count:
            break
        if ex not in chosen:
            chosen.append(ex)
    return chosen


def select_examples(examples: list[dict], role: str | None = None, exclude_games: tuple[str, ...] = (), extra_moves: tuple[str, ...] = ()) -> dict:
    """{"own": B・A の例(型ごと), "opponent": 相手側の例, "avoid": 裏目に出た動き}。extra_moves の型は、多めに選ぶ。"""
    pool = [e for e in examples if e["game"] not in exclude_games and e.get("outcome") != "avoid"]
    avoid = [e for e in examples if e["game"] not in exclude_games and e.get("outcome") == "avoid"]
    own_pool = [e for e in pool if e["tier"] in (1, 2)]
    taken: set[str] = set()
    own: dict[str, list[dict]] = {}
    for move, count in PER_MOVE.items():
        count += 1 if move in extra_moves else 0
        chosen = pick(own_pool, move, count, role, taken)
        taken |= {e["id"] for e in chosen}
        if chosen:
            own[move] = chosen
    opponent_pool = [e for e in pool if e["tier"] == 3]
    opponent: list[dict] = []
    for move in OPPONENT_MOVES:
        for ex in pick(opponent_pool, move, 1, "人狼", {e["id"] for e in opponent}):
            opponent.append(ex)
    return {"own": own, "opponent": opponent, "avoid": avoid}


def render_example(ex: dict) -> str:
    who = {1: "B", 2: "A"}.get(ex["tier"], "相手側")
    head = f"- ({who}・{ex['role']}・{ex['register']}) 状況: {ex['situation']}"
    body = "\n".join(f"  {line}" for line in ex["utterance"].split("\n"))
    return f"{head}\n  発言:\n{body}"


def render_avoid(ex: dict) -> str:
    body = " / ".join(ex["utterance"].split("\n"))
    return f"- 状況: {ex['situation']}\n  発言: {body}\n  なぜ避けるか: {ex.get('note', '裏目に出た')}"


def render_examples(selected: dict) -> str:
    out = [
        "# 発言例",
        "",
        "名前は A, B, C などの代名。実戦では、ログにある実際の名前を使う。発言そのものを写さず、型と呼吸を写す。",
        "状況は、受けている発言の要約。B・A は、実戦ログの話者。",
    ]
    for move, rows in selected["own"].items():
        out += ["", f"【{move}】", *[render_example(ex) for ex in rows]]
    if selected["opponent"]:
        out += ["", "【相手側の動き(読む対象。真似ない)】", *[render_example(ex) for ex in selected["opponent"]]]
    if selected["avoid"]:
        out += ["", "【避ける動き(実戦で裏目に出た。真似ない)】", *[render_avoid(ex) for ex in selected["avoid"]]]
    return "\n".join(out)


FORMAT_HEADING = "## 11. 出力形式"
CHAT_FORMAT = """## 11. 出力形式

ユーザーが貼ったログに対して、次の形で返す。JSON は使わない。

読み: 狙いと、要注意の相手を1〜3行で。
投稿案(上から順に貼る):
[1] (返信先 #12 #15 / rebut,tally)
そのまま貼れる発言
[2] (返信先 なし / probe)
そのまま貼れる発言
投票先: 名前(まだなら「未定」)

- 返信先は、ログの発言番号(#N)。ログに番号がなければ、「〇〇の『…』」のように短く示す。最大4件。
- 型は、「型」の名前から1〜3個。
- 投稿案は最大4件。名前の欄(「名前:」)は付けない。改行は、論点を分けるときだけ。
- 今は書かないほうがよいときは、投稿案を空にして、理由を1行で書く。
"""


def fill(text: str, me: str | None, role: str | None, register: str) -> str:
    return text.replace("{me}", me or ME_UNSET).replace("{role}", role or ROLE_UNSET).replace("{register}", register)


def build_system(
    root: Path,
    me: str | None = None,
    role: str | None = None,
    register: str = "タメ口",
    exclude_games: tuple[str, ...] = (),
    extra_moves: tuple[str, ...] = (),
    output_format: str = "json",
) -> list[dict]:
    """APIの system に渡すブロック。前の2つはキャッシュする(ゲーム中は変わらない)。
    output_format は json(API の tool 用)か chat(Claude のチャットやプロジェクトに貼る用。読める形で返させる)。"""
    knowledge = Path(root) / "knowledge"
    instructions = (knowledge / "bot_prompt.md").read_text(encoding="utf-8")
    if output_format == "chat":
        instructions = instructions[: instructions.index(FORMAT_HEADING)] + CHAT_FORMAT
    instructions = fill(instructions, me, role, register)
    style = (knowledge / "discussion_style.md").read_text(encoding="utf-8")
    reference = "\n".join(
        [
            "# 型の一覧(出力の moves に使う)",
            "",
            moves_text(style),
            "",
            "# 語彙(理解用。チャットでは説明せず、そのまま使う)",
            "",
            vocabulary_text(style),
        ]
    )
    selected = select_examples(load_examples(knowledge / "examples.jsonl"), role, exclude_games, extra_moves)
    return [
        {"type": "text", "text": instructions + "\n\n" + reference, "cache_control": CACHE},
        {"type": "text", "text": render_examples(selected), "cache_control": CACHE},
    ]


def as_text(blocks: list[dict]) -> str:
    return "\n\n".join(b["text"] for b in blocks)
