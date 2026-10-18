"""匿名化済みログから、発言の長さや形についての簡単な統計を出す。"""
from __future__ import annotations

import re
from statistics import median

from .parse import EXTENSION

MENTION = re.compile(r"《([A-Z])》")
QUESTION = re.compile(r"[?？]")
LAUGH = re.compile(r"[wｗ]|笑")
SHORT, MID = 15, 60  # 文字数の区切り: 〜15 / 16〜60 / 61〜

COLUMNS = [
    "role", "messages", "share", "chars_total", "chars_share", "chars_mean", "chars_median",
    "chars_max", "short", "mid", "long", "questions", "laughs", "mentions", "back_to_back",
]


def discussion_days(game: dict) -> int:
    """議論した日数(昼の局面に入った日の数)。占いなしの小人数戦は1日、占い入りは2日になる。"""
    return max((e["day"] for e in game["events"] if e["phase"] == "day"), default=0)


def extension_by_day(game: dict) -> dict[int, int]:
    """日ごとの延長の秒数。延長の通知が出た日に数える(ログから分かる)。"""
    seconds: dict[int, int] = {}
    for e in game["events"]:
        if e["kind"] == "system" and (m := EXTENSION.search(e["text"])):
            seconds[e["day"]] = seconds.get(e["day"], 0) + int(m["seconds"])
    return seconds


def discussion_minutes(game: dict) -> float | None:
    """1日あたりの議論時間(ingest で指定)× 議論した日数 + 延長分。指定がなければ None。"""
    base = game.get("discussion_seconds")
    if base is None:
        return None
    return (base * discussion_days(game) + game.get("extension_seconds", 0)) / 60


def day_breakdown(game: dict) -> list[dict]:
    """議論が2日以上あるゲームの、日ごとの発言数・字数・議論時間(延長込み)。1日だけなら空。"""
    days = discussion_days(game)
    if days < 2:
        return []
    base = game.get("discussion_seconds")
    extension = extension_by_day(game)
    rows = []
    for day in range(1, days + 1):
        speech = [e for e in game["events"] if e["kind"] == "speech" and e["day"] == day]
        chars = sum(len(e["text"].replace("\n", "")) for e in speech)
        row = {
            "day": day,
            "messages": len(speech),
            "chars": chars,
            "extension_seconds": extension.get(day, 0),
            "speakers": {},
        }
        for e in speech:
            s = row["speakers"].setdefault(e["speaker"], {"messages": 0, "chars": 0})
            s["messages"] += 1
            s["chars"] += len(e["text"].replace("\n", ""))
        if base is not None:
            minutes = (base + row["extension_seconds"]) / 60
            row["seconds"] = base + row["extension_seconds"]
            row["chars_per_minute"] = round(chars / minutes, 1)
            row["messages_per_minute"] = round(len(speech) / minutes, 1)
            for s in row["speakers"].values():
                s["chars_per_minute"] = round(s["chars"] / minutes, 1)
        rows.append(row)
    return rows


def speech_stats(game: dict) -> dict:
    speakers: dict[str, dict] = {}
    previous = None
    for e in game["events"]:
        if e["kind"] != "speech":
            continue
        who, text = e["speaker"], e["text"]
        s = speakers.setdefault(
            who, {"lengths": [], "questions": 0, "laughs": 0, "mentions": 0, "back_to_back": 0}
        )
        s["lengths"].append(len(text.replace("\n", "")))
        s["questions"] += bool(QUESTION.search(text))
        s["laughs"] += bool(LAUGH.search(text))
        s["mentions"] += sum(1 for name in MENTION.findall(text) if name != who)
        s["back_to_back"] += previous == who
        previous = who

    total = sum(len(s["lengths"]) for s in speakers.values())
    total_chars = sum(sum(s["lengths"]) for s in speakers.values())
    minutes = discussion_minutes(game)
    summary = {}
    for who, s in speakers.items():
        lengths = s.pop("lengths")
        summary[who] = {
            "role": game["players"].get(who, {}).get("role"),
            "messages": len(lengths),
            "share": round(len(lengths) / total, 2),
            "chars_total": sum(lengths),
            "chars_share": round(sum(lengths) / total_chars, 2),
            **({"chars_per_minute": round(sum(lengths) / minutes, 1)} if minutes else {}),
            "chars_mean": round(sum(lengths) / len(lengths), 1),
            "chars_median": median(lengths),
            "chars_max": max(lengths),
            "short": sum(n <= SHORT for n in lengths),
            "mid": sum(SHORT < n <= MID for n in lengths),
            "long": sum(n > MID for n in lengths),
            **s,
        }
    result = {
        "game_id": game["game_id"],
        "speech_messages": total,
        "chars_total": total_chars,
        "extension_seconds": game.get("extension_seconds", 0),
        "speakers": summary,
    }
    if minutes:
        result["minutes"] = round(minutes, 1)
        result["chars_per_minute"] = round(total_chars / minutes, 1)
        result["messages_per_minute"] = round(total / minutes, 1)
    if days := day_breakdown(game):  # 複数日のゲームだけ。1日のゲームの出力は変わらない
        result["days"] = days
    return result


def format_stats(stats: dict) -> str:
    header = (
        f"game {stats['game_id']}: 発言 {stats['speech_messages']} 件 / {stats['chars_total']} 字"
        f" / 延長 {stats['extension_seconds']} 秒"
    )
    columns = list(COLUMNS)
    if "minutes" in stats:
        header += (
            f" / 議論 {stats['minutes']} 分 → {stats['chars_per_minute']} 字/分,"
            f" {stats['messages_per_minute']} 件/分"
        )
        columns.append("chars_per_minute")
    lines = [header, "speaker\t" + "\t".join(columns)]
    for who, s in sorted(stats["speakers"].items()):
        lines.append(who + "\t" + "\t".join(str(s[c]) for c in columns))
    for row in stats.get("days", []):
        line = f"day {row['day']}: 発言 {row['messages']} 件 / {row['chars']} 字 / 延長 {row['extension_seconds']} 秒"
        if "seconds" in row:
            line += (
                f" / 議論 {row['seconds']} 秒 → {row['chars_per_minute']} 字/分,"
                f" {row['messages_per_minute']} 件/分"
            )
        lines.append(line)
        for who, s in sorted(row["speakers"].items()):
            cells = [f"{s['messages']} 件", f"{s['chars']} 字"]
            if "chars_per_minute" in s:
                cells.append(f"{s['chars_per_minute']} 字/分")
            lines.append(f"  {who}\t" + "\t".join(cells))
    return "\n".join(lines)
