"""knowledge/ の整合性チェックと、発言の型の表の同期。

発言例(examples.jsonl)を正とし、ガイド(discussion_style.md)の「発言の型」の表の
「主な話者」「例」の列を作り直す(sync_table)。check は、発言例と正規化ログの突き合わせ
(返信先 reply_to を含む)、表のずれ、実名の混入、冗長・説明口調の語、原文との長い一致を調べる。
ログのない環境では、ログを使うチェックは飛ばす。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

REGISTERS = ("敬語", "タメ口")
TIER_OF = {"B": 1, "A": 2}  # ベース話者 B、次点話者 A。それ以外は 3
GROUP = {1: "B", 2: "A", 3: "他"}
BANNED = ["つまり", "例えば", "たとえば", "ではないでしょうか", "ということです", "という点", "ご自身"]
OVERLAP_LIMIT = 18  # 原文との逐語一致がこの字数以上なら、言い換え不足とみなす
MAX_REPLY_TO = 4  # 1つの発言が受ける発言の数の上限(これ以上は絞って付ける)
MIN_NAME_LENGTH = 2  # 実名の混入を調べる名前の最小の長さ(1文字の名前は誤検出になる)
PLACEHOLDER = "(要記入)"
ROW = re.compile(r"^\| (?P<tag>[a-z_]+) \|")


def load_examples(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def summarize(examples: list[dict]) -> dict[str, tuple[Counter, list[str]]]:
    """型 → (話者グループごとの件数, 例の id)。"""
    summary: dict[str, tuple[Counter, list[str]]] = {}
    for ex in examples:
        for move in ex["moves"]:
            counts, ids = summary.setdefault(move, (Counter(), []))
            counts[GROUP[ex["tier"]]] += 1
            ids.append(ex["id"])
    return summary


def format_speakers(counts: Counter) -> str:
    return " ".join(f"{group}{counts[group]}" for group in ("B", "A", "他") if counts[group])


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_move_row(line: str) -> bool:
    return ROW.match(line) is not None and len(table_cells(line)) == 5


def parse_table(text: str) -> dict[str, list[str]]:
    return {table_cells(line)[0]: table_cells(line) for line in text.splitlines() if is_move_row(line)}


def sync_table(text: str, examples: list[dict]) -> str:
    """表の「主な話者」「例」を発言例から作り直す。表にない型は末尾に足す(説明は要記入)。"""
    summary = summarize(examples)
    lines = text.splitlines()
    seen: set[str] = set()
    last_row = None
    for i, line in enumerate(lines):
        if not is_move_row(line):
            continue
        cells = table_cells(line)
        seen.add(cells[0])
        last_row = i
        if cells[0] in summary:
            counts, ids = summary[cells[0]]
            cells[3], cells[4] = format_speakers(counts), ", ".join(ids)
            lines[i] = "| " + " | ".join(cells) + " |"
    if last_row is not None:
        lines[last_row + 1:last_row + 1] = [
            f"| {tag} | {PLACEHOLDER} | {PLACEHOLDER} | {format_speakers(counts)} | {', '.join(ids)} |"
            for tag, (counts, ids) in summary.items()
            if tag not in seen
        ]
    return "\n".join(lines) + "\n"


def longest_overlap(text: str, raw: str) -> int:
    match = SequenceMatcher(None, text, raw, autojunk=False).find_longest_match(0, len(text), 0, len(raw))
    return match.size


def check_reply_to(ex: dict, game: dict | None) -> list[str]:
    """reply_to: その発言が受けている発言の seq。空なら話題の開始・挨拶・システム通知への反応。"""
    name = ex["id"]
    reply_to = ex.get("reply_to")
    if not isinstance(reply_to, list) or not all(isinstance(n, int) for n in reply_to):
        return [f"{name}: reply_to が整数のリストになっていない"]
    problems = []
    if reply_to != sorted(set(reply_to)):
        problems.append(f"{name}: reply_to が昇順・重複なしになっていない")
    if len(reply_to) > MAX_REPLY_TO:
        problems.append(f"{name}: reply_to が{MAX_REPLY_TO}件を超えている(主な返信先に絞る)")
    problems += [f"{name}: reply_to の seq {n} が自分(seq {ex['seq']})以降" for n in reply_to if n >= ex["seq"]]
    if game is not None:
        speech = {e["seq"] for e in game["events"] if e["kind"] == "speech"}
        problems += [f"{name}: reply_to の seq {n} は発言ではない" for n in reply_to if n < ex["seq"] and n not in speech]
    return problems


def check_example(ex: dict, game: dict | None) -> list[str]:
    name = ex["id"]
    problems = []
    expected_tier = TIER_OF.get(ex["speaker"], 3)
    if ex.get("tier") != expected_tier:
        problems.append(f"{name}: tier が {ex.get('tier')}(話者 {ex['speaker']} なら {expected_tier})")
    if ex.get("register") not in REGISTERS:
        problems.append(f"{name}: register が {ex.get('register')!r}(敬語かタメ口)")
    if not ex["utterance"].strip() or not ex["situation"].strip():
        problems.append(f"{name}: utterance か situation が空")
    if ex.get("outcome") not in (None, "avoid"):
        problems.append(f"{name}: outcome が {ex['outcome']!r}(avoid か、なし)")
    problems += [f"{name}: 説明口調・冗長の語 {word!r} が発言にある" for word in BANNED if word in ex["utterance"]]
    problems += check_reply_to(ex, game)
    if game is not None:
        event = next((e for e in game["events"] if e["seq"] == ex["seq"]), None)
        if event is None or event["kind"] != "speech":
            problems.append(f"{name}: seq {ex['seq']} は発言ではない")
        else:
            if event["speaker"] != ex["speaker"]:
                problems.append(f"{name}: 話者がログと違う({ex['speaker']} ≠ {event['speaker']})")
            if game["players"][event["speaker"]]["role"] != ex["role"]:
                problems.append(f"{name}: 役職がログと違う")
            if event["phase"] != ex["phase"]:
                problems.append(f"{name}: 局面がログと違う({ex['phase']} ≠ {event['phase']})")
    return problems


def check_table(table: dict[str, list[str]], summary: dict[str, tuple[Counter, list[str]]]) -> list[str]:
    problems = []
    for tag, (counts, ids) in summary.items():
        cells = table.get(tag)
        if cells is None:
            problems.append(f"型 {tag} が表にない(sync を実行)")
            continue
        if PLACEHOLDER in cells[1] + cells[2]:
            problems.append(f"型 {tag} の説明が未記入")
        if cells[3] != format_speakers(counts) or cells[4] != ", ".join(ids):
            problems.append(f"型 {tag} の表が発言例とずれている(sync を実行)")
    problems += [f"型 {tag} は表にあるが発言例がない" for tag in table if tag not in summary]
    return problems


def tracked_files(root: Path) -> list[Path]:
    files = [root / "README.md", root / ".gitignore"]
    for pattern in ("knowledge/*", "zinro_learn/*.py", "zinro_bot/*.py", "zinro_bot/*.html", "tests/*.py", ".claude/skills/*/SKILL.md"):
        files += sorted(root.glob(pattern))
    return [path for path in files if path.is_file()]


def check_names(root: Path) -> list[str]:
    """匿名化の対応表(git 管理外)にある実名が、git 管理のファイルに混ざっていないか。1文字の名前は、文中の文字と区別できないので調べない。"""
    names: set[str] = set()
    for path in (root / "logs/private").glob("*.players.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        names |= set(data["players"].values()) | set(data["aliases"])
    names = {name for name in names if len(name) >= MIN_NAME_LENGTH}
    problems = []
    for path in tracked_files(root):
        text = path.read_text(encoding="utf-8")
        problems += [f"{path.relative_to(root)} に実名 {name!r} がある" for name in sorted(names) if name in text]
    return problems


def check_overlap(examples: list[dict], root: Path) -> list[str]:
    raws: dict[str, str] = {}
    problems = []
    for ex in examples:
        path = root / "logs/raw" / f"{ex['game']}.txt"
        if not path.exists():
            continue
        raw = raws.setdefault(ex["game"], path.read_text(encoding="utf-8").replace("\n", ""))
        size = longest_overlap(ex["utterance"].replace("\n", ""), raw)
        if size >= OVERLAP_LIMIT:
            problems.append(f"{ex['id']}: 原文と{size}字連続で一致(言い換え不足)")
    return problems


def load_games(root: Path, ids: set[str]) -> dict[str, dict]:
    games = {}
    for game_id in sorted(ids):
        path = root / "logs/normalized" / f"{game_id}.json"
        if path.exists():
            games[game_id] = json.loads(path.read_text(encoding="utf-8"))
    return games


def check(root: Path) -> list[str]:
    examples = load_examples(root / "knowledge/examples.jsonl")
    style = (root / "knowledge/discussion_style.md").read_text(encoding="utf-8")
    games = load_games(root, {ex["game"] for ex in examples})
    problems: list[str] = []
    if [ex["id"] for ex in examples] != [f"ex{i:02d}" for i in range(1, len(examples) + 1)]:
        problems.append("id が ex01, ex02, ... の順になっていない")
    for ex in examples:
        problems += check_example(ex, games.get(ex["game"]))
    problems += check_table(parse_table(style), summarize(examples))
    problems += check_names(root)
    problems += check_overlap(examples, root)
    return problems
