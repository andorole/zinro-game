"""対戦中のログ(コピペしたテキスト)を、ボットが読める卓の状況に直す。

学習用の `zinro_learn.parse` は、終わったログ(全員の役職通知がある)を前提にしている。
対戦中は、自分の役職通知しかなく、他のプレイヤーの名前は発言の行から拾うしかない。
発言者は、指定された名前、役職通知・投票の行に出る名前、2回以上行頭に出る名前から決める。
1回しか出ない名前は、名前らしいときだけ発言者として扱い、警告に出す。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from zinro_learn.parse import (
    DUMMY,
    EXTENSION,
    ROLE_NOTICE,
    SEP,
    SYSTEM,
    VOTE_LINE,
    advance,
    directed_pattern,
)

# 行頭の「名前:」。名前の欄にコロン・矢印・空白は入らない
CANDIDATE = re.compile(rf"^(?P<name>[^\s:：→「」『』()（）\[\]]{{1,20}}){SEP}(?P<text>.*)$")
# 1回しか出ない行頭の語のうち、名前ではなく見出しとして使われやすいもの
LABELS = {"例", "結論", "理由", "補足", "注", "追記", "備考", "質問", "回答", "結果", "予想", "仮定", "要約", "前提", "根拠", "返信", "引用"}
VOTE_COMMAND = re.compile(r"投票@(?P<actor>[^→]+)→(?P<target>.+)$")


@dataclass
class Post:
    seq: int
    speaker: str
    text: str


@dataclass
class Table:
    me: str | None
    role: str | None
    players: list[str]
    posts: list[Post]
    notes: list[tuple[int, str]]  # (直前の発言の番号, 鯖の通知)
    phase: str  # day / vote / night / unknown
    extensions: int
    warnings: list[str] = field(default_factory=list)

    def last_seq(self) -> int:
        return self.posts[-1].seq if self.posts else 0


@dataclass
class _Line:
    kind: str  # speech / system / private / ignore
    text: str
    speaker: str | None = None
    to: str | None = None


def _known_pattern(names: set[str]) -> re.Pattern | None:
    if not names:
        return None
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"^(?P<name>{alternatives}){SEP}(?P<text>.*)$")


def _classify(line: str, directed: re.Pattern) -> _Line | None:
    """名前を使わずに種類が決まる行。決まらなければ None(発言か、前の発言の続き)。"""
    if m := directed.match(line):
        src, dst, text = m["src"], m["dst"], m["text"]
        if src == "鯖":
            return _Line("private", text, to=dst)
        return _Line("ignore", text, speaker=src, to=dst)  # コマンド・霊界・独り言・人狼チャット
    if m := SYSTEM.match(line):
        return _Line("system", m["text"])
    return None


def _first_pass(lines: list[str], players: set[str]) -> tuple[dict[str, str], Counter, set[str]]:
    """役職通知(名前 → 役職)、行頭の名前の出現数、投票の行に出る名前を集める。"""
    directed = directed_pattern(players)
    roles: dict[str, str] = {}
    starts: Counter = Counter()
    voters: set[str] = set()
    for line in lines:
        if m := ROLE_NOTICE.match(line):
            roles[m["name"]] = m["role"]
            continue
        if m := directed.match(line):
            if m["dst"] == "GM" and (v := VOTE_COMMAND.search(m["text"])):
                voters |= {v["actor"], v["target"]}
            continue
        if SYSTEM.match(line):
            continue
        if m := VOTE_LINE.match(line):
            voters |= {m["player"], m["voted_for"]}
            continue
        if m := CANDIDATE.match(line):
            starts[m["name"]] += 1
    return roles, starts, voters


def _speakers(starts: Counter, roles: dict[str, str], voters: set[str], explicit: set[str], me: str | None) -> tuple[set[str], list[str]]:
    warnings: list[str] = []
    names = set(explicit)
    if explicit:
        return names | ({me} if me else set()), warnings
    names |= {n for n in roles if n != DUMMY} | {n for n in voters if n != DUMMY}
    if me:
        names.add(me)
    names |= {n for n, c in starts.items() if c >= 2}
    for name, count in starts.items():
        if name in names or count != 1 or name in LABELS or name == "鯖":
            continue
        if len(name) <= 12:
            names.add(name)
            warnings.append(f"{name!r} は1回しか出ないが、発言者として扱った(違うなら --players で名前を指定)")
    return names, warnings


def _split(lines: list[str], names: set[str]) -> list[_Line]:
    speech = _known_pattern(names)
    directed = directed_pattern(names)
    out: list[_Line] = []
    for line in lines:
        if (item := _classify(line, directed)) is not None:
            out.append(item)
        elif speech and (m := speech.match(line)):
            out.append(_Line("speech", m["text"], speaker=m["name"]))
        elif out and out[-1].kind in ("speech", "system"):
            out[-1].text += "\n" + line
        # 先頭の続き行や、無視する行の続きは捨てる
    return out


def detect_newest_first(items: list[_Line]) -> bool | None:
    """朝・投票時間・開始の通知と発言の位置関係で並び順を決める。決められなければ None。"""
    speech = [i for i, m in enumerate(items) if m.kind == "speech"]
    if not speech:
        return None

    def find(words: tuple[str, ...]) -> list[int]:
        return [i for i, m in enumerate(items) if m.kind == "system" and any(w in m.text for w in words)]

    morning = find(("朝になりました",))
    if morning:
        if min(morning) > max(speech):
            return True
        if max(morning) < min(speech):
            return False
    vote = find(("投票時間になりました",))
    if vote:
        if max(vote) < min(speech):
            return True
        if min(vote) > max(speech):
            return False
    begin = find(("ゲームを開始します",)) + [i for i, m in enumerate(items) if m.kind == "private" and m.text.startswith("あなたは【")]
    if begin:
        if min(begin) > max(speech):
            return True
        if max(begin) < min(speech):
            return False
    return None


def parse_table(
    text: str,
    me: str | None = None,
    role: str | None = None,
    players: list[str] | None = None,
    order: str = "auto",
) -> Table:
    """order は auto / newest-first / oldest-first。判定できないときは、新しい発言が上と仮定する。"""
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    explicit = {p for p in (players or []) if p}
    roles, starts, voters = _first_pass(lines, explicit)
    names, warnings = _speakers(starts, roles, voters, explicit, me)
    items = _split(lines, names)

    newest_first = {"newest-first": True, "oldest-first": False}.get(order)
    if newest_first is None:
        newest_first = detect_newest_first(items)
        if newest_first is None:
            newest_first = True
            warnings.append("並び順を判定できないので、新しい発言が上と仮定した(違うなら --order oldest-first)")
    if newest_first:
        items.reverse()

    # 自分の名前と役職。役職通知が1人分だけなら、それが自分
    if me is None and len(roles) == 1:
        me = next(iter(roles))
    if role is None and me in roles:
        role = roles[me]
    if me is None:
        warnings.append("自分の名前が分からない(--me で指定)")
    if role is None:
        warnings.append("自分の役職が分からない(--role で指定)")

    posts: list[Post] = []
    notes: list[tuple[int, str]] = []
    phase, day, extensions = "unknown", 0, 0
    for item in items:
        if item.kind == "speech":
            posts.append(Post(len(posts) + 1, item.speaker, item.text))
        elif item.kind == "system":
            phase, day = advance(phase if phase != "unknown" else "setup", day, item.text)
            if EXTENSION.search(item.text):
                extensions += 1
            if _worth_noting(item.text):
                notes.append((len(posts), item.text.splitlines()[0]))
    if phase == "setup":
        phase = "unknown"

    speakers = [p.speaker for p in posts]
    order_seen = list(dict.fromkeys([*([me] if me else []), *speakers]))
    return Table(me, role, order_seen, posts, notes, phase, extensions, warnings)


def _worth_noting(text: str) -> bool:
    return any(w in text for w in ("延長", "朝になりました", "夜になりました", "投票時間", "死亡しました", "処刑されます", "勝利"))


PHASE_TEXT = {
    "day": "昼の議論中",
    "vote": "投票時間(話すのをやめる。投票先だけ決める)",
    "night": "夜",
    "unknown": "局面は不明(議論中と見なす)",
}


def render(table: Table, remaining: int | None = None, register: str = "タメ口") -> str:
    """モデルに渡す、卓の状況と発言の一覧(古い順)。"""
    head = [
        "# 卓の状況",
        f"- 自分の名前: {table.me or '不明'}",
        f"- 自分の役職: {table.role or '不明'}",
        f"- 発言した人: {'、'.join(table.players) if table.players else 'まだいない'}",
        f"- 局面: {PHASE_TEXT.get(table.phase, table.phase)}",
        f"- 延長: {table.extensions}回(議論の時間は 300 + 90 × 回数 秒)",
    ]
    if remaining is not None:
        head.append(f"- 残り時間: {remaining}秒")
    head.append(f"- 発言の語調: {register}")
    notes = list(table.notes)
    body = ["", "# ここまでの発言(古い順。番号は返信先の指定に使う)"]
    if not table.posts:
        body.append("(まだ誰も発言していない)")
    idx = 0
    for before in range(0, len(table.posts) + 1):
        while idx < len(notes) and notes[idx][0] == before:
            body.append(f"[通知] {notes[idx][1]}")
            idx += 1
        if before < len(table.posts):
            post = table.posts[before]
            first, *rest = post.text.split("\n")
            body.append(f"#{post.seq} {post.speaker}: {first}")
            body += [f"    {line}" for line in rest]
    return "\n".join(head + body)
