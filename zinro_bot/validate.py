"""モデルの出力(JSON)を検査して、貼れる形に直す。

直せるもの(名前の欄、前後の空白、返信先の並び)は直し、直せないもの(説明口調の語、方言、箇条書き、
例文の写し、役職の漏れ、長すぎる発言)は problems に出す。problems がある投稿は、やり直しを求めるか捨てる。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from zinro_learn.check import BANNED, MAX_REPLY_TO, OVERLAP_LIMIT, longest_overlap

# 依頼者の指示で避ける、説明口調・AI っぽい言い回し(check の BANNED に足した分)
AI_TONE = ["ご指摘", "整理すると", "まとめると", "言えるでしょう", "いかがでしょうか", "させていただ", "以下の", "ポイントは", "考えられます"]
# 方言(真似しない)。標準語の「やろう」「やっている」などに当たらないように、語尾の形で拾う
DIALECT = re.compile(r"(やな(?=[。、…！？\s]|$)|やろ(?!う)|やで(?=[。、…！？\s]|$)|やん(?=[。、…！？\s]|$)|やから|んよな|んやな|ねん(?=[。、…！？\s]|$)|あかん|ほんま|しとる|おらん|せやな|せやけど)")
META = re.compile(r"(AI|ＡＩ|ボット|Claude|クロード|プロンプト|言語モデル)")
LIST_LINE = re.compile(r"^\s*([-*・•]|\d+[.)]|#{1,6}\s)")
MARKUP = re.compile(r"(\*\*|`{1,3}|^#{1,6}\s)", re.M)
INTERNAL_REF = re.compile(r"#\d+")
SELF_AS_WOLF = re.compile(r"(自分|私|俺|僕|オレ|ぼく)は(人狼|狼)(です|だ|だよ|なの|だぞ)")

MAX_CHARS = 240
SOFT_CHARS = 200
MAX_LINES = 5
MAX_POSTS = 4
MAX_MOVES = 3


@dataclass
class Draft:
    text: str
    reply_to: list[int]
    moves: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Turn:
    read: dict
    posts: list[Draft]
    vote: str | None
    silence: str
    problems: list[str] = field(default_factory=list)  # 捨てた投稿とその理由
    warnings: list[str] = field(default_factory=list)


def turn_to_dict(turn: Turn) -> dict:
    """検査を通った分を、出力形式(JSON)の形に戻す。保存や、--json の表示に使う。"""
    return {
        "read": turn.read,
        "posts": [{"reply_to": p.reply_to, "moves": p.moves, "text": p.text} for p in turn.posts],
        "vote": turn.vote,
        "silence": turn.silence,
    }


def normalize_text(text: str, me: str | None) -> str:
    text = str(text).replace("\r", "").strip()
    if me:
        text = re.sub(rf"^{re.escape(me)}[:：]\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def check_text(text: str, examples: list[str]) -> tuple[list[str], list[str]]:
    """(problems, warnings)。problems があれば、その投稿は貼れない。"""
    problems: list[str] = []
    warnings: list[str] = []
    if not text:
        return ["空の発言"], warnings
    problems += [f"説明口調・AI っぽい語 {w!r}" for w in [*BANNED, *AI_TONE] if w in text]
    if m := DIALECT.search(text):
        problems.append(f"方言 {m.group(0)!r}(標準語にする)")
    if any(LIST_LINE.match(line) for line in text.split("\n")) or MARKUP.search(text):
        problems.append("箇条書き・見出し・マークダウンの記号")
    if INTERNAL_REF.search(text):
        problems.append("内部の発言番号(#12 など)が text に入っている")
    if len(text) > MAX_CHARS:
        problems.append(f"長すぎる({len(text)}字。{SOFT_CHARS}字以内、論点ごとに分ける)")
    elif len(text) > SOFT_CHARS:
        warnings.append(f"長め({len(text)}字)")
    if text.count("\n") + 1 > MAX_LINES:
        problems.append(f"行が多すぎる({text.count(chr(10)) + 1}行)")
    if SELF_AS_WOLF.search(text):
        problems.append("自分が狼だと言っている(役職の漏れ、または役と合わない発言)")
    for ex in examples:
        size = longest_overlap(text, ex)
        if size >= OVERLAP_LIMIT:
            problems.append(f"発言例の写し({size}字連続で一致)")
            break
    if META.search(text):
        warnings.append("AI・ボットなどに言及している(聞かれたときの返答なら可)")
    return problems, warnings


def _as_int(value) -> int | None:
    text = str(value).lstrip("#").strip()
    return int(text) if text.isdigit() else None


def clean_reply_to(raw, last_seq: int) -> tuple[list[int], list[str]]:
    warnings: list[str] = []
    values = raw if isinstance(raw, list) else []
    numbers = sorted({n for n in map(_as_int, values) if n is not None})
    valid = [n for n in numbers if 1 <= n <= last_seq]
    if len(valid) != len(numbers):
        warnings.append("存在しない発言番号を返信先から除いた")
    if len(valid) > MAX_REPLY_TO:
        warnings.append(f"返信先を{MAX_REPLY_TO}件に絞った")
        valid = valid[-MAX_REPLY_TO:]
    return valid, warnings


def build_turn(data: dict, *, me: str | None, players: list[str], last_seq: int, known_moves: set[str], examples: list[str]) -> Turn:
    """モデルの出力 data を検査する。貼れない投稿は posts から除き、problems に理由を残す。"""
    read = data.get("read") if isinstance(data.get("read"), dict) else {}
    vote = data.get("vote")
    turn = Turn(read, [], None, str(data.get("silence") or ""))
    if isinstance(vote, str) and vote.strip() and vote.strip().lower() != "null":
        if vote.strip() in players and vote.strip() != me:
            turn.vote = vote.strip()
        else:
            turn.warnings.append(f"投票先 {vote!r} は参加者にいないので無視した")
    posts = data.get("posts") if isinstance(data.get("posts"), list) else []
    if len(posts) > MAX_POSTS:
        turn.warnings.append(f"投稿が{len(posts)}件あったので、先頭の{MAX_POSTS}件にした")
        posts = posts[:MAX_POSTS]
    for index, item in enumerate(posts, 1):
        if not isinstance(item, dict):
            turn.problems.append(f"投稿{index}: 形式が違う")
            continue
        text = normalize_text(item.get("text", ""), me)
        problems, warnings = check_text(text, examples)
        reply_to, reply_warnings = clean_reply_to(item.get("reply_to"), last_seq)
        moves = [m for m in (item.get("moves") if isinstance(item.get("moves"), list) else []) if m in known_moves][:MAX_MOVES]
        if problems:
            turn.problems += [f"投稿{index}: {p}" for p in problems]
            continue
        turn.posts.append(Draft(text, reply_to, moves, [*warnings, *reply_warnings]))
    if not turn.posts and not turn.silence and not turn.problems:
        turn.silence = "(理由なし)"
    return turn
