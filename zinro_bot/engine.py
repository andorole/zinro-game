"""1ターン分の処理: 卓の状況 → プロンプト → モデル → 検査 → 貼れる発言。

検査で落ちた投稿があれば、理由を添えて出し直させる(最大 max_retries 回)。それでも直らない投稿は捨てる。
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from zinro_learn.check import load_examples, parse_table as parse_move_table

from .prompt import build_system, read_section
from .transcript import Table, render
from .validate import Turn, build_turn


@dataclass
class Context:
    """ゲーム中は変わらないもの。system は、キャッシュするブロックを含む。"""
    system: list[dict]
    known_moves: set[str]
    examples: list[str]  # 全発言例の発言(発言例の写しを検出するため)


@dataclass
class Result:
    turn: Turn
    usage: list[dict] = field(default_factory=list)
    attempts: int = 1
    seconds: float = 0.0  # 呼び出し全体(出し直しと点検を含む)の所要時間


def make_context(
    root: Path,
    me: str | None,
    role: str | None,
    register: str = "タメ口",
    exclude_games: tuple[str, ...] = (),
    extra_moves: tuple[str, ...] = (),
) -> Context:
    root = Path(root)
    style = (root / "knowledge/discussion_style.md").read_text(encoding="utf-8")
    moves = set(parse_move_table(read_section(style, "発言の型")))
    examples = [e["utterance"] for e in load_examples(root / "knowledge/examples.jsonl")]
    system = build_system(root, me, role, register, exclude_games, extra_moves)
    return Context(system, moves, examples)


def hints(table: Table) -> str:
    """ログから機械的に拾えるメモ。モデルが拾い漏らしやすい、未回収の問いと、量の釣り合いを補う。"""
    me = table.me
    lines = ["# 機械的に拾ったメモ(参考。判断はあなたがする)"]
    if not table.posts:
        return "\n".join([*lines, "- まだ誰も発言していない。挨拶と、短い冗談か最初の話題から入る"])
    mine = [p for p in table.posts if p.speaker == me]
    last_mine = mine[-1].seq if mine else 0
    after = [p for p in table.posts if p.seq > last_mine and p.speaker != me]
    if mine:
        lines.append(f"- 自分の最後の発言: #{last_mine}。それ以降の他人の発言: {len(after)}件")
    else:
        lines.append(f"- 自分はまだ発言していない。他人の発言: {len(after)}件")
    if me:
        named = [p.seq for p in after if me in p.text]
        if named:
            lines.append("- 自分の名前が出ている発言(最後の発言以降): " + "、".join(f"#{n}" for n in named))
    asked = [p.seq for p in after if "？" in p.text or "?" in p.text]
    if asked:
        lines.append("- 問いを含む発言(最後の発言以降): " + "、".join(f"#{n}" for n in asked))
    recent = table.posts[-8:]
    mean = sum(len(p.text) for p in recent) / len(recent)
    lines.append(f"- 直近{len(recent)}件の平均は{mean:.0f}字。部屋のテンポは、これに合わせる(短いやりとりなら1件・短く、書き合いが長ければ長く)。発言は全部で{len(table.posts)}件")
    if mine:
        lines.append("- 自分の直近の発言(口調・立場・冗談の続きとして書く): " + " / ".join(f"#{p.seq}「{p.text.splitlines()[0][:40]}」" for p in mine[-3:]))
    chars = Counter()
    for p in table.posts:
        chars[p.speaker] += len(p.text)
    total = sum(chars.values()) or 1
    share = "、".join(f"{name} {count / total:.0%}" for name, count in chars.most_common())
    lines.append(f"- 文字量の割合: {share}(B・A は部屋全体の4〜5割を書いた。自分が少なすぎないか)")
    return "\n".join(lines)


def memory_text(memory: dict | None, table: Table) -> str:
    """前のターンの自分のメモ。判断の一貫性を保つため(状況が変わっていれば更新させる)。"""
    if not memory or memory.get("me") != table.me or memory.get("posts_seen", 0) > len(table.posts):
        return ""
    lines = ["# 前回の自分のメモ(参考。状況が変わっていれば更新する)"]
    if memory.get("aim"):
        lines.append(f"- 狙い: {memory['aim']}")
    for name, note in (memory.get("players") or {}).items():
        lines.append(f"- {name}: {note}")
    for item in memory.get("pending") or []:
        lines.append(f"- 未回収: {item}")
    if memory.get("swing"):
        lines.append(f"- 第三者: {memory['swing']}")
    if memory.get("vote"):
        lines.append(f"- 投票先の見込み: {memory['vote']}")
    return "\n".join(lines)


def make_memory(table: Table, turn: Turn) -> dict:
    read = turn.read or {}
    return {
        "me": table.me, "posts_seen": len(table.posts), "aim": read.get("aim", ""),
        "players": read.get("players") or {}, "pending": read.get("pending") or [],
        "swing": read.get("swing", ""), "vote": turn.vote,
    }


def user_message(table: Table, remaining: int | None = None, register: str = "タメ口", memory: dict | None = None) -> str:
    parts = [render(table, remaining, register), hints(table), memory_text(memory, table)]
    parts.append("上の状況で、あなたが次に書く発言を、指示の出力形式で提出する。")
    return "\n\n".join(part for part in parts if part)


def feedback(turn: Turn) -> str:
    lines = ["次の問題があったので、直して出し直す。問題のなかった投稿は、そのまま残す。"]
    lines += [f"- {problem}" for problem in turn.problems]
    return "\n".join(lines)


CRITIC_NOTE = """提出した案を、次の観点で点検して、直した最終案を同じ形式で出し直す。直す必要がなければ、そのまま出し直す。
1. ログにない発言を、あったことにしていないか。発言者の取り違え、引用の間違いはないか。
2. 自分の過去の発言(口調、立場、票先の見込み、条件つきの宣言)と矛盾していないか。
3. 役職の漏れ(人狼のとき)や、もう一人の村人との不要な対立はないか。
4. すでに誰かが言ったことの繰り返しや、新しい材料のない発言がないか。件数と長さは局面に合っているか(雑談なら1件・短く)。
5. 説明口調、冗長、方言、箇条書きがないか。"""


def respond(
    client,
    ctx: Context,
    table: Table,
    remaining: int | None = None,
    register: str = "タメ口",
    max_retries: int = 2,
    memory: dict | None = None,
    critic: bool = False,
) -> Result:
    """検査に落ちた投稿は、理由を添えて出し直させる。critic なら、通った案をもう一度点検させる(通らなければ元の案)。"""
    started = time.monotonic()
    messages = [{"role": "user", "content": user_message(table, remaining, register, memory)}]
    usage: list[dict] = []

    def ask() -> tuple[object, Turn]:
        reply = client.complete(ctx.system, messages)
        usage.append(reply.usage)
        turn = build_turn(
            reply.data,
            me=table.me,
            players=table.players,
            last_seq=table.last_seq(),
            known_moves=ctx.known_moves,
            examples=ctx.examples,
        )
        return reply, turn

    def append(reply, note: str, is_error: bool) -> None:
        messages.append({"role": "assistant", "content": reply.content})
        if reply.tool_use_id:
            result = {"type": "tool_result", "tool_use_id": reply.tool_use_id, "content": note}
            if is_error:
                result["is_error"] = True
            messages.append({"role": "user", "content": [result]})
        else:
            messages.append({"role": "user", "content": note})

    attempts = 0
    for attempts in range(1, max_retries + 2):
        reply, turn = ask()
        if not turn.problems or attempts > max_retries:
            break
        append(reply, feedback(turn), True)  # 直させる(tool を使わない応答なら、文章で返す)
    if critic and turn.posts and not turn.problems:
        append(reply, CRITIC_NOTE, False)
        _, revised = ask()
        attempts += 1
        if revised.posts and not revised.problems:
            turn = revised
    return Result(turn, usage, attempts, time.monotonic() - started)
