"""zinro.net 形式の人狼ログ(コピペしたテキスト)を、時系列のイベント列に変換する。

ログは新しい発言が上に来る。1発言は複数行になることがあり、2行目以降には
「名前:」が付かない。発言者名は役職通知(鯖→名前: あなたは【役職】です)から集める。
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass

SEP = r"[:：]\s?"
ROLE_NOTICE = re.compile(rf"^鯖→(?P<name>[^:：]+?){SEP}あなたは【(?P<role>[^】]+)】です$")
ROLE_TEXT = re.compile(r"^あなたは【(?P<role>[^】]+)】です$")
SYSTEM = re.compile(rf"^鯖{SEP}(?P<text>.*)$")
DIRECTED = re.compile(rf"^(?P<src>[^:：→]+)→(?P<dst>[^:：→]+?){SEP}(?P<text>.*)$")
COMMAND_BODY = re.compile(r"^(?P<action>[^@]+)@(?P<actor>[^→]+)→(?P<target>.+)$")
VOTE_LINE = re.compile(r"^(?P<player>.+?)\((?P<received>\d+)票\)の投票先→(?P<voted_for>.+)$")
EXECUTED = re.compile(r"投票の結果【(?P<name>[^】]+)】さんが処刑されます")
DEATH = re.compile(r"^(?P<name>.+?)さんが死亡しました$")
SETUP = re.compile(r"^役職設定【(?P<setup>.+)】$")
WINNER = re.compile(r"【(?P<team>[^】]+)】の勝利です")
EXTENSION = re.compile(r"時間を(?P<seconds>\d+)秒延長しました")
DUMMY = "初日犠牲者"


@dataclass
class Message:
    kind: str  # system / private / command / speech / spirit / self / directed
    text: str
    speaker: str | None = None
    to: str | None = None


def directed(src: str, dst: str, text: str) -> Message:
    """「送り手→宛先: 本文」の行。宛先で種類が決まる(霊界は死者・観戦者のチャット)。"""
    if src == "鯖":
        return Message("private", text, to=dst)
    if dst == "GM":
        return Message("command", text, speaker=src)
    if dst == "霊界":
        return Message("spirit", text, speaker=src)
    if dst == src:
        return Message("self", text, speaker=src)
    return Message("directed", text, speaker=src, to=dst)


def collect_roles(lines: list[str]) -> dict[str, str]:
    roles = {}
    for line in lines:
        if m := ROLE_NOTICE.match(line):
            roles[m["name"]] = m["role"]
    return roles


def split_messages(lines: list[str], names: set[str]) -> list[Message]:
    speech = None
    if names:
        alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        speech = re.compile(rf"^(?P<name>{alternatives}){SEP}(?P<text>.*)$")
    messages: list[Message] = []
    for line in lines:
        if m := DIRECTED.match(line):
            messages.append(directed(m["src"], m["dst"], m["text"]))
        elif m := SYSTEM.match(line):
            messages.append(Message("system", m["text"]))
        elif speech and (m := speech.match(line)):
            messages.append(Message("speech", m["text"], speaker=m["name"]))
        elif messages:
            messages[-1].text += "\n" + line
        else:
            raise ValueError(f"先頭の行が発言の開始として認識できません: {line!r}")
    return messages


def is_begin(m: Message) -> bool:
    if m.kind == "private" and ROLE_TEXT.match(m.text):
        return True
    return m.kind == "system" and ("ゲームを開始します" in m.text or SETUP.match(m.text) is not None)


def is_end(m: Message) -> bool:
    return m.kind == "system" and WINNER.search(m.text) is not None


def detect_newest_first(messages: list[Message]) -> bool | None:
    """開始側の目印と終了側の目印の位置関係から並び順を決める。決められなければ None。"""
    begin = [i for i, m in enumerate(messages) if is_begin(m)]
    end = [i for i, m in enumerate(messages) if is_end(m)]
    if not begin or not end:
        return None
    if min(begin) > max(end):
        return True
    if max(begin) < min(end):
        return False
    return None


def advance(phase: str, day: int, text: str) -> tuple[str, int]:
    """鯖の通知で局面を進める。day は「迎えた朝の数」(最初の夜は 0)。"""
    if "朝になりました" in text:
        return "day", day + 1
    if "夜になりました" in text:
        return "night", day
    if "投票時間になりました" in text:
        return "vote", day
    if WINNER.search(text):
        return "end", day
    return phase, day


def system_fields(text: str) -> dict:
    fields: dict = {}
    if text.startswith("【投票結果】"):
        fields["votes"] = [
            {"player": v["player"], "received": int(v["received"]), "voted_for": v["voted_for"]}
            for line in text.splitlines()[1:]
            if (v := VOTE_LINE.match(line))
        ]
        if executed := EXECUTED.search(text):
            fields["executed"] = executed["name"]
    elif death := DEATH.match(text):
        fields["death"] = death["name"]
    return fields


def annotate(messages: list[Message]) -> list[dict]:
    phase, day = "setup", 0
    events = []
    for seq, m in enumerate(messages, 1):
        if m.kind == "system":
            phase, day = advance(phase, day, m.text)
        event = {
            "seq": seq,
            "phase": phase,
            "day": day,
            "kind": m.kind,
            "speaker": m.speaker,
            "to": m.to,
            "text": m.text,
        }
        if m.kind == "command" and (body := COMMAND_BODY.match(m.text)):
            event.update(body.groupdict())
        elif m.kind == "private" and (role := ROLE_TEXT.match(m.text)):
            event["role"] = role["role"]
        elif m.kind == "system":
            event.update(system_fields(m.text))
        events.append(event)
    return events


def find_in_system(events: list[dict], pattern: re.Pattern, group: str) -> str | None:
    for e in events:
        if e["kind"] == "system" and (m := pattern.search(e["text"])):
            return m[group]
    return None


def extension_seconds(events: list[dict]) -> int:
    return sum(
        int(m["seconds"])
        for e in events
        if e["kind"] == "system" and (m := EXTENSION.search(e["text"]))
    )


def parse_game(text: str, game_id: str, order: str = "auto") -> dict:
    """order は auto / newest-first / oldest-first。"""
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    roles = collect_roles(lines)
    messages = split_messages(lines, set(roles))
    newest_first = {"newest-first": True, "oldest-first": False}.get(order)
    if newest_first is None:
        newest_first = detect_newest_first(messages)
    if newest_first is None:
        raise ValueError("ログの並び順を判定できません。--order newest-first / oldest-first で指定してください")
    if newest_first:
        messages.reverse()
    events = annotate(messages)
    return {
        "game_id": game_id,
        "setup": find_in_system(events, SETUP, "setup"),
        "winner": find_in_system(events, WINNER, "team"),
        "extension_seconds": extension_seconds(events),
        "players": {
            name: {"role": role, **({"dummy": True} if name == DUMMY else {})}
            for name, role in roles.items()
        },
        "events": events,
    }


def speaking_order(game: dict) -> list[str]:
    seen: list[str] = []
    for e in game["events"]:
        if e["kind"] == "speech" and e["speaker"] not in seen:
            seen.append(e["speaker"])
    return seen


def observer_names(game: dict) -> list[str]:
    """プレイヤー以外で書き込んだ人(霊界で話す観戦者など)。"""
    roles = {info["role"] for info in game["players"].values()}
    seen: list[str] = []
    for e in game["events"]:
        name = e["speaker"]
        if name and name not in game["players"] and name not in roles and name not in seen:
            seen.append(name)
    return seen


def build_mapping(game: dict, explicit: dict[str, str] | None = None) -> dict[str, str]:
    """実名 → A, B, C...(プレイヤー)、O1, O2...(観戦者など)。指定のない人は順に割り当てる。ダミーは対象外。"""
    mapping = dict(explicit or {})
    free = (c for c in string.ascii_uppercase if c not in mapping.values())
    for name in [*speaking_order(game), *game["players"]]:
        if name != DUMMY and name not in mapping:
            mapping[name] = next(free)
    for i, name in enumerate(observer_names(game), 1):
        mapping.setdefault(name, f"O{i}")
    return mapping


def anonymize(game: dict, mapping: dict[str, str], aliases: dict[str, str] | None = None) -> dict:
    """名前の欄は A などの文字に、本文中の名前は《A》に置き換える。aliases は 通称 → 実名。"""
    names = dict(mapping)
    for alias, real in (aliases or {}).items():
        if real not in mapping:
            raise ValueError(f"通称 {alias!r} の指す {real!r} がプレイヤーにいません")
        names[alias] = mapping[real]

    def label(name):
        return mapping.get(name, name) if name else name

    if names:
        pattern = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))

        def scrub(text):
            return pattern.sub(lambda m: f"《{names[m.group(0)]}》", text)
    else:
        def scrub(text):
            return text

    events = []
    for source in game["events"]:
        e = dict(source)
        for key in ("speaker", "to", "actor", "target", "executed", "death"):
            if e.get(key):
                e[key] = label(e[key])
        e["text"] = scrub(e["text"])
        if "votes" in e:
            e["votes"] = [
                {**v, "player": label(v["player"]), "voted_for": label(v["voted_for"])}
                for v in e["votes"]
            ]
        events.append(e)
    players = {label(name): info for name, info in game["players"].items()}
    return {**game, "players": players, "events": events}
