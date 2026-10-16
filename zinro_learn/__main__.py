"""使い方:
  python -m zinro_learn ingest logs/raw/<id>.txt --players "実名1=A,実名2=B" --alias 通称=実名1 --discussion-seconds 300
  python -m zinro_learn stats logs/normalized/<id>.json [...]
  python -m zinro_learn sync     # 発言例から、ガイドの「発言の型」の表を作り直す
  python -m zinro_learn check    # knowledge/ の整合性を調べる(問題があれば終了コード 1)
  python -m zinro_learn structure  # 連投と返信の型(1発言に1返信ではない構造)を数える
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyze import format_stats, speech_stats
from .check import check, load_examples, load_games, sync_table
from .parse import anonymize, build_mapping, parse_game
from .structure import format_structure


def parse_pairs(value: str) -> dict[str, str]:
    pairs = (item.split("=", 1) for item in value.split(",") if item)
    return {key.strip(): val.strip() for key, val in pairs}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def ingest(args) -> None:
    raw = Path(args.raw)
    game = parse_game(raw.read_text(encoding="utf-8"), game_id=args.id or raw.stem, order=args.order)
    if args.discussion_seconds is not None:
        game["discussion_seconds"] = args.discussion_seconds
    mapping = build_mapping(game, parse_pairs(args.players))
    aliases = {}
    for item in args.alias:
        aliases.update(parse_pairs(item))
    anonymized = anonymize(game, mapping, aliases)

    out = Path(args.out_dir) / f"{game['game_id']}.json"
    private = Path(args.private_dir) / f"{game['game_id']}.players.json"
    write_json(out, anonymized)
    write_json(private, {"players": {label: name for name, label in mapping.items()}, "aliases": aliases})
    print(f"{out}: {len(anonymized['events'])} events, winner={anonymized['winner']}")
    print(f"{private}: 匿名名と実名の対応(git 管理外)")


def stats(args) -> None:
    for path in args.normalized:
        game = json.loads(Path(path).read_text(encoding="utf-8"))
        print(format_stats(speech_stats(game)) + "\n")


def sync(args) -> None:
    root = Path(args.root)
    path = root / "knowledge/discussion_style.md"
    path.write_text(
        sync_table(path.read_text(encoding="utf-8"), load_examples(root / "knowledge/examples.jsonl")),
        encoding="utf-8",
    )
    print(f"{path}: 発言の型の表を更新した(「(要記入)」の説明は手で書く)")


def structure(args) -> None:
    root = Path(args.root)
    examples = load_examples(root / "knowledge/examples.jsonl")
    games = load_games(root, {ex["game"] for ex in examples})
    print(format_structure(games, examples))


def run_check(args) -> None:
    problems = check(Path(args.root))
    for problem in problems:
        print("-", problem)
    if problems:
        raise SystemExit(1)
    print("問題なし")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="zinro_learn")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="生ログを時系列に直し、匿名化して保存する")
    p.add_argument("raw")
    p.add_argument("--id", help="省略時はファイル名")
    p.add_argument("--order", choices=["auto", "newest-first", "oldest-first"], default="auto")
    p.add_argument("--players", default="", help='"実名=A,実名=B"。指定のない人は発言順に割り当てる')
    p.add_argument("--alias", action="append", default=[], help='"通称=実名"。本文中の通称も匿名化する')
    p.add_argument("--out-dir", default="logs/normalized")
    p.add_argument("--private-dir", default="logs/private")
    p.add_argument("--discussion-seconds", type=int, help="1日あたりの議論時間(延長前の秒数)。話量(字/分)の計算に使う")
    p.set_defaults(func=ingest)

    p = sub.add_parser("stats", help="発言の長さなどの統計を表示する")
    p.add_argument("normalized", nargs="+")
    p.set_defaults(func=stats)

    p = sub.add_parser("sync", help="発言例から、ガイドの「発言の型」の表を作り直す")
    p.add_argument("--root", default=".")
    p.set_defaults(func=sync)

    p = sub.add_parser("structure", help="連投と返信の型を数える")
    p.add_argument("--root", default=".")
    p.set_defaults(func=structure)

    p = sub.add_parser("check", help="knowledge/ の整合性を調べる")
    p.add_argument("--root", default=".")
    p.set_defaults(func=run_check)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
