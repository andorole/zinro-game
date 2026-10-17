"""返信の構造: 1つの発言に1つ返すだけではない、という観察を数える。

- 連投: 同じ人が続けて投稿した回数(run_lengths)。考えながら小分けに送る、畳みかける、など。
- 返信の型: 発言例の reply_to(その発言が受けている発言)から、返信先の取り方を分ける(reply_kind)。
    opener   返信先なし(話題の開始、挨拶、システム通知への反応)
    continue 自分の直前の発言の続き・補足
    direct   直前の他人の発言への返信
    skip     直前の他人の発言を飛ばして、それより前の発言に返す(遅れた返信、並行して走る話題)
    multi    他人の発言を2つ以上まとめて受ける
"""
from __future__ import annotations

from collections import Counter
from statistics import median

KINDS = ("opener", "continue", "direct", "skip", "multi")
GROUPS = ("B", "A", "他")
TIER_GROUP = {1: "B", 2: "A", 3: "他"}


def speech_events(game: dict) -> list[dict]:
    return [e for e in game["events"] if e["kind"] == "speech"]


def group_of(speaker: str) -> str:
    return speaker if speaker in ("A", "B") else "他"


def run_lengths(game: dict) -> list[tuple[str, int, int]]:
    """同じ人の連続した発言の列: (話者, 件数, 最初の seq)。システム通知や霊界は間に入っても途切れない。"""
    runs: list[list] = []
    for e in speech_events(game):
        if runs and runs[-1][0] == e["speaker"]:
            runs[-1][1] += 1
        else:
            runs.append([e["speaker"], 1, e["seq"]])
    return [tuple(run) for run in runs]


def run_summary(games: list[dict]) -> dict[str, dict]:
    """話者グループ(B / A / 他)ごとの連投の数え上げ。"""
    summary = {g: {"posts": 0, "runs": Counter(), "in_runs": 0, "longest": 0} for g in GROUPS}
    for game in games:
        for speaker, length, _ in run_lengths(game):
            s = summary[group_of(speaker)]
            s["posts"] += length
            s["runs"][min(length, 4)] += 1
            s["in_runs"] += length if length >= 2 else 0
            s["longest"] = max(s["longest"], length)
    return summary


def reply_kind(ex: dict, speech: list[dict]) -> tuple[str, list[int]]:
    """発言例の返信の型と、他人の発言までの距離(間にある発言の数 + 1)。"""
    me, targets = ex["speaker"], ex["reply_to"]
    if not targets:
        return "opener", []
    by_seq = {e["seq"]: i for i, e in enumerate(speech)}
    here = by_seq[ex["seq"]]
    others = [t for t in targets if speech[by_seq[t]]["speaker"] != me]
    if not others:
        return "continue", []
    distances = [here - by_seq[t] for t in others]
    if len(others) >= 2:
        return "multi", distances
    latest_other = max(i for i in range(here) if speech[i]["speaker"] != me)
    return ("direct" if by_seq[others[0]] == latest_other else "skip"), distances


def reply_summary(examples: list[dict], games: dict[str, dict]) -> dict[str, dict]:
    """話者グループごとの、返信の型の件数と距離。"""
    summary = {g: {"kinds": Counter(), "distances": [], "skip_distances": [], "targets": []} for g in GROUPS}
    speeches = {gid: speech_events(game) for gid, game in games.items()}
    for ex in examples:
        if ex["game"] not in games:
            continue
        kind, distances = reply_kind(ex, speeches[ex["game"]])
        s = summary[TIER_GROUP[ex["tier"]]]
        s["kinds"][kind] += 1
        s["distances"] += distances
        if kind == "skip":
            s["skip_distances"] += distances
        s["targets"].append(len(ex["reply_to"]))
    return summary


def format_structure(games: dict[str, dict], examples: list[dict]) -> str:
    lines = ["連投(同じ人が続けて投稿した列。話者グループ別、全ログ合計)", "group\tposts\t連投に入る投稿\t割合\t1件\t2件\t3件\t4件以上\t最長"]
    for group, s in run_summary(list(games.values())).items():
        share = s["in_runs"] / s["posts"] if s["posts"] else 0
        lines.append(
            f"{group}\t{s['posts']}\t{s['in_runs']}\t{share:.0%}\t"
            + "\t".join(str(s["runs"][n]) for n in (1, 2, 3, 4)) + f"\t{s['longest']}"
        )
    lines += ["", "返信の型(発言例の reply_to から。話者グループ別)", "group\t件数\t" + "\t".join(KINDS) + "\t平均の返信先数\tskip の距離(中央値)"]
    for group, s in reply_summary(examples, games).items():
        total = sum(s["kinds"].values())
        if not total:
            continue
        cells = "\t".join(f"{s['kinds'][k]}({s['kinds'][k] / total:.0%})" for k in KINDS)
        mean_targets = sum(s["targets"]) / len(s["targets"])
        skip = f"{median(s['skip_distances']):g}" if s["skip_distances"] else "-"
        lines.append(f"{group}\t{total}\t{cells}\t{mean_targets:.1f}\t{skip}")
    return "\n".join(lines)
