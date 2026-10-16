"""匿名化済みログから、発言の長さや形についての簡単な統計を出す。"""
from __future__ import annotations

import re
from statistics import median

MENTION = re.compile(r"《([A-Z])》")
QUESTION = re.compile(r"[?？]")
LAUGH = re.compile(r"[wｗ]|笑")
SHORT, MID = 15, 60  # 文字数の区切り: 〜15 / 16〜60 / 61〜

COLUMNS = [
    "role", "messages", "share", "chars_total", "chars_share", "chars_mean", "chars_median",
    "chars_max", "short", "mid", "long", "questions", "laughs", "mentions", "back_to_back",
]


def discussion_minutes(game: dict) -> float | None:
    """1日あたりの議論時間(ingest で指定)× 議論した日数 + 延長分。指定がなければ None。"""
    base = game.get("discussion_seconds")
    if base is None:
        return None
    days = max((e["day"] for e in game["events"] if e["phase"] == "day"), default=0)
    return (base * days + game.get("extension_seconds", 0)) / 60


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
    summary = {}
    for who, s in speakers.items():
        lengths = s.pop("lengths")
        summary[who] = {
            "role": game["players"].get(who, {}).get("role"),
            "messages": len(lengths),
            "share": round(len(lengths) / total, 2),
            "chars_total": sum(lengths),
            "chars_share": round(sum(lengths) / total_chars, 2),
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
    if minutes := discussion_minutes(game):
        result["minutes"] = round(minutes, 1)
        result["chars_per_minute"] = round(total_chars / minutes, 1)
    return result


def format_stats(stats: dict) -> str:
    header = (
        f"game {stats['game_id']}: 発言 {stats['speech_messages']} 件 / {stats['chars_total']} 字"
        f" / 延長 {stats['extension_seconds']} 秒"
    )
    if "minutes" in stats:
        header += f" / 議論 {stats['minutes']} 分 → {stats['chars_per_minute']} 字/分"
    lines = [header, "speaker\t" + "\t".join(COLUMNS)]
    for who, s in sorted(stats["speakers"].items()):
        lines.append(who + "\t" + "\t".join(str(s[c]) for c in COLUMNS))
    return "\n".join(lines)
