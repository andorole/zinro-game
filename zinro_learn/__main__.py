"""使い方:
  python -m zinro_learn ingest logs/raw/<id>.txt --players "実名1=A,実名2=B" --alias 通称=実名1 --discussion-seconds 300
      ふつうの語句でもある名前(例: ハンドル名が「なるほどね」)は --plain-word 名前 を付ける(複数指定可)。
      logs/private/<id>.players.json の plain_words に入り、check の実名混入の検査から外れる。
  python -m zinro_learn stats logs/normalized/<id>.json [...]
  python -m zinro_learn timeline logs/normalized/<id>.json [...]   # 役職、夜の行動と通知、死亡、人狼の夜チャットを、夜と昼の順に並べる
  python -m zinro_learn board knowledge/boards/<id>.json [--stage N]   # 盤面整理: 公開された情報に合う役職の割り当て(真・狼・狂)、確定した黒白、縄
  python -m zinro_learn board --patterns [--setup 12a-neko|11a|10a-kari]   # 名乗りの数(占い-霊)ごとの、名乗りの種類の組み合わせと、定番／ありうる／まれ
  python -m zinro_learn progress [--setup 12a-neko|11a|10a-kari] [--random-white on|off] [--missing on|off] --seers 3 [--result A:B:黒] [--guard none|medium|blacksayer|env|either] [--cat off|hidden|open|counter|gidra] [--hunter off|gidra|fake] [--bites grey claim] [--no-seer-results] [--no-rpp] [--seers-first] [--no-reads]   # 進行の比較(占いロラ・グレランなど)の、村の勝率の試算
  python -m zinro_learn playout [--setup 12a-neko|11a|10a-kari] --seers 2 [--result A:C:白 ...] [--policy posterior] [--bite claim|grey] [--seed 1]   # 1試合を動かして、昼1・昼2・昼3・昼4…の盤面を出す
  python -m zinro_learn sync     # 発言例から、ガイドの「発言の型」の表を作り直す
  python -m zinro_learn check    # knowledge/ の整合性を調べる(問題があれば終了コード 1)
  python -m zinro_learn structure  # 連投と返信の型(1発言に1返信ではない構造)を数える
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyze import format_stats, speech_stats
from .board import DEFAULT_SETUP, SETUPS, load_record, make_board, patterns_text, record_report, setup_roles, stage_report
from .check import check, load_examples, load_games, sync_table
from .parse import anonymize, build_mapping, parse_game
from .playout import playout_text
from .progress import ALL_POLICIES, BITE_NAME, BITES, CAT_NAME, CATS, GUARD_NAME, HUNTER_NAME, HUNTERS, POLICY_NAME, compare_policies, compare_text, hit_rates
from .roles import format_timeline
from .structure import format_structure


def parse_pairs(value: str) -> dict[str, str]:
    pairs = (item.split("=", 1) for item in value.split(",") if item)
    return {key.strip(): val.strip() for key, val in pairs}


def parse_names(values: list[str]) -> list[str]:
    """--plain-word の値(複数指定も、1つの値のコンマ区切りも可)を、重複なく並べる。"""
    names: list[str] = []
    for value in values:
        for name in (item.strip() for item in value.split(",")):
            if name and name not in names:
                names.append(name)
    return names


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
    plain_words = parse_names(args.plain_word)
    unknown = [name for name in plain_words if name not in mapping and name not in aliases]
    if unknown:
        raise ValueError(f"--plain-word の {unknown} が、プレイヤー名にも通称にもありません")
    anonymized = anonymize(game, mapping, aliases)

    out = Path(args.out_dir) / f"{game['game_id']}.json"
    private = Path(args.private_dir) / f"{game['game_id']}.players.json"
    table = {"players": {label: name for name, label in mapping.items()}, "aliases": aliases}
    if plain_words:  # 指定のないログの対応表は、これまでと同じ形のまま
        table["plain_words"] = plain_words
    write_json(out, anonymized)
    write_json(private, table)
    print(f"{out}: {len(anonymized['events'])} events, winner={anonymized['winner']}")
    print(f"{private}: 匿名名と実名の対応(git 管理外)")


def stats(args) -> None:
    for path in args.normalized:
        game = json.loads(Path(path).read_text(encoding="utf-8"))
        print(format_stats(speech_stats(game)) + "\n")


def timeline(args) -> None:
    for path in args.normalized:
        game = json.loads(Path(path).read_text(encoding="utf-8"))
        print(format_timeline(game) + "\n")


def board(args) -> None:
    if args.patterns:
        cfg = SETUPS[args.setup]
        roles, missing = setup_roles(args.setup, None if args.missing is None else args.missing == "on")
        print(patterns_text(roles=roles, name=cfg.name, missing=missing) if (args.setup != DEFAULT_SETUP or missing) else patterns_text())
        return
    if not args.record:
        raise SystemExit("盤面の記録(knowledge/boards/<id>.json)か --patterns を指定してください")
    record = load_record(args.record)
    print(stage_report(record, args.stage) if args.stage is not None else record_report(record))


def build_board(args):
    """progress・playout 共通: 配役 args.setup の、占い args.seers 人・霊能(最後の1人)の盤面。結果は A:B:黒 の形。"""
    if not 1 <= args.seers <= 5:
        raise SystemExit("--seers は 1〜5")
    results = []
    for item in args.result:
        player, target, color = item.split(":")
        results.append({"player": player, "target": target, "color": color})
    return make_board(args.setup, args.seers, results, random_white=None if args.random_white is None else args.random_white == "on",
                      missing=None if args.missing is None else args.missing == "on")


def play_options(args) -> dict:
    """progress・playout 共通: 試合の前提(護衛・猫又・同数の票・先黒吊りか・村の読み・狩人)。"""
    cfg = SETUPS[args.setup]
    return dict(guard=None if args.guard == "none" else args.guard, seer_results=not args.no_seer_results,
                cat=args.cat or ("gidra" if "猫又" in cfg.roles else "off"), rpp=not args.no_rpp, black_first=not args.seers_first,
                reads=not args.no_reads, hunter=args.hunter)


def playout(args) -> None:
    board = build_board(args)
    print(playout_text(board, args.policy, args.bite, args.seed, **play_options(args)))


def progress(args) -> None:
    """配役 args.setup(既定は12A猫。ダミーを除く参加者)の、占い args.seers 人・霊能(最後の1人)の盤面で、進行ごとの村の勝率を試算する。結果は A:B:黒 の形。"""
    cfg = SETUPS[args.setup]
    board = build_board(args)
    cat = args.cat or ("gidra" if "猫又" in cfg.roles else "off")
    guard = None if args.guard == "none" else args.guard
    rates = hit_rates(board)
    seers = "、".join(f"{p} {v * 100:.1f}%" for p, v in rates["占い"].items())
    title = (f"{cfg.name}・" + ("白ランオン・" if board.random_white else "") + ("役欠けあり・" if board.dummy else "") + f"{args.seers}-1" + ("・" + "、".join(args.result) if args.result else "・結果なし") + f"・{GUARD_NAME[guard]}"
             + ("・占いの夜の結果なし" if args.no_seer_results else "・占いの夜の結果あり") + f"・{CAT_NAME[cat]}"
             + ("・同数の票の操作なし" if args.no_rpp else "・同数は抽選(RPP)あり") + ("・占い吊り優先(黒先は占いのあと)" if args.seers_first else "・先黒吊り")
             + ("・村の読みなし" if args.no_reads else "・村は霊能の報告で占いを読む") + (f"・{HUNTER_NAME[args.hunter]}" if args.hunter != "off" else ""))
    print(f"昼1の1本目の吊りが人狼に当たる見込み(厳密): 占いの名乗り {seers} / 灰1人 {rates['灰'] * 100:.1f}%({rates['灰の人数']}人)")
    print(compare_text(board, title, args.n, args.seed, guard=guard, seer_results=not args.no_seer_results, cat=cat, rpp=not args.no_rpp,
                       black_first=not args.seers_first, reads=not args.no_reads, hunter=args.hunter, bites=tuple(args.bites)))
    if args.posterior:
        print(f"尤度吊り(毎朝、公開された情報に合う世界を数え直して、人狼の見込みがいちばん高い人を吊る)との比較(同じ世界の引きで {args.posterior_n} 回):")
        for bite in args.bites:
            r = compare_policies(board, ALL_POLICIES, bite, args.posterior_n, args.seed, args.workers, **play_options(args))
            print(f"  {BITE_NAME[bite]}: " + " | ".join(f"{POLICY_NAME[p]} {r[p] * 100:.1f}%" for p in ALL_POLICIES))


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


def add_board_options(p) -> None:
    """progress・playout 共通の、配役・盤面・前提の選択肢。"""
    p.add_argument("--setup", choices=list(SETUPS), default=DEFAULT_SETUP,
                   help="配役: 12a-neko=12A猫(既定)、11a=11A、10a-kari=10A狩(11A・10A狩は白ランオン。10A狩の人数は推測)")
    p.add_argument("--random-white", choices=["on", "off"], default=None, help="白ランオン(本物の占いの初日の結果は無作為な白)。省略すると、配役の約束事のとおり")
    p.add_argument("--missing", choices=["on", "off"], default=None, help="役欠け(ダミーの役職が人狼以外のどれかで、占い・霊能・狩人なども欠けうる)。省略すると、配役の約束事のとおり(12A猫・11A・10A狩とも、あり)")
    p.add_argument("--seers", type=int, default=3, help="占いの名乗りの人数(A から順に)")
    p.add_argument("--result", action="append", default=[], help="占いの初手の結果。例: A:B:黒(A が B に黒)。複数指定可")
    p.add_argument("--guard", choices=["none", "medium", "blacksayer", "env", "either"], default="env",
                   help="狩人の護衛: none=護衛なし、medium=霊護衛固定、blacksayer=黒出し占い護衛固定、env=環境の護衛(黒を出した占い、なければ霊能。既定)、either=占い(真目)か霊能のどちらかを無作為に護衛(依頼者: 護衛するのもどちらかでいい)")
    p.add_argument("--cat", choices=CATS, default=None,
                   help="猫又の扱い: off=力を数えない、hidden=隠れている、open=名乗っていて吊らず噛まない、counter=名乗り、対抗猫が出る(猫吊り)、"
                        "gidra=隠れていて、黒を刺されたら・指定されたら名乗る(12A猫の既定。猫又のいない配役は off)")
    p.add_argument("--hunter", choices=HUNTERS, default="gidra",
                   help="狩人の狩CO(ギドラ): gidra=吊りを指定された狩人が名乗る(既定。10A狩・11A は必ず=依頼者: 当然狩CO。12A猫は GIDRA_HUNTER の割合=依頼者: 場合あり。仮)。そのほか、黒を出されたとき・グレーが狭まって詰むとき(依頼者の答え)・GJのあとにも名乗る、off=名乗らない、fake=gidra に加えて、昼1の指定で人外が偽の狩人を名乗る(仮の割合)")
    p.add_argument("--no-reads", action="store_true", help="村の読みを入れない(霊能の報告で偽の占いを見抜く動きなし。11A のメモと同じ前提)")
    p.add_argument("--seers-first", action="store_true", help="占い吊り優先: 占いの名乗りを先に吊り、黒先は占いを吊り終えてから(標準は先黒吊り)")
    p.add_argument("--no-rpp", action="store_true", help="同数のときの票(人外側の PP・RPP)を入れない(11A のメモと同じ前提)")
    p.add_argument("--no-seer-results", action="store_true", help="占いの2日目以降の結果を入れない(最初の試算と同じ)")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="zinro_learn")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="生ログを時系列に直し、匿名化して保存する")
    p.add_argument("raw")
    p.add_argument("--id", help="省略時はファイル名")
    p.add_argument("--order", choices=["auto", "newest-first", "oldest-first"], default="auto")
    p.add_argument("--players", default="", help='"実名=A,実名=B"。指定のない人は発言順に割り当てる')
    p.add_argument("--alias", action="append", default=[], help='"通称=実名"。本文中の通称も匿名化する')
    p.add_argument(
        "--plain-word", action="append", default=[],
        help="ふつうの語句でもある名前(例: ハンドル名が「なるほどね」)。check の実名混入の検査から外す。複数指定可",
    )
    p.add_argument("--out-dir", default="logs/normalized")
    p.add_argument("--private-dir", default="logs/private")
    p.add_argument("--discussion-seconds", type=int, help="1日あたりの議論時間(延長前の秒数)。話量(字/分)の計算に使う")
    p.set_defaults(func=ingest)

    p = sub.add_parser("stats", help="発言の長さなどの統計を表示する")
    p.add_argument("normalized", nargs="+")
    p.set_defaults(func=stats)

    p = sub.add_parser("timeline", help="役職・夜の行動・通知・死亡・人狼の夜チャットを、夜と昼の順に表示する")
    p.add_argument("normalized", nargs="+")
    p.set_defaults(func=timeline)

    p = sub.add_parser("board", help="盤面整理: 公開された情報に合う役職の割り当てと、確定した黒白、縄を出す")
    p.add_argument("record", nargs="?", help="盤面の記録(knowledge/boards/<id>.json)")
    p.add_argument("--stage", type=int, help="段階の番号(0から)。省略すると全部")
    p.add_argument("--patterns", action="store_true", help="名乗りの数(占い-霊)ごとの、名乗りの種類の組み合わせ")
    p.add_argument("--setup", choices=list(SETUPS), default=DEFAULT_SETUP, help="配役(--patterns で使う。既定は12A猫)")
    p.add_argument("--missing", choices=["on", "off"], default=None, help="役欠け(--patterns で使う。省略すると、配役の約束事のとおり)")
    p.set_defaults(func=board)

    p = sub.add_parser("progress", help="進行の比較: 占いロラ・グレランなどの、村の勝率を試算する(12A猫、占い N 人・霊能 K)")
    add_board_options(p)
    p.add_argument("--n", type=int, default=20000, help="試算の回数")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--posterior", action="store_true", help="尤度吊り(毎朝、人狼の見込みがいちばん高い人を吊る)も比べる(遅い)")
    p.add_argument("--posterior-n", type=int, default=2000, help="尤度吊りを比べるときの回数")
    p.add_argument("--bites", nargs="+", choices=list(BITES), default=list(BITES), help="比べる狼の噛み方(既定は grey claim。claim=名乗りを噛む=占い・霊能の候補だけ噛む。依頼者: それ以外は噛まれない)")
    p.add_argument("--workers", type=int, default=4, help="尤度吊りを比べるときの並列数")
    p.set_defaults(func=progress)

    p = sub.add_parser("playout", help="1試合を動かして、昼1・昼2・昼3・昼4…の盤面(人狼の見込みと吊り先)を出す")
    add_board_options(p)
    p.add_argument("--policy", choices=list(ALL_POLICIES), default="posterior", help="進行(既定は尤度吊り)")
    p.add_argument("--bite", choices=list(BITES), default="claim", help="狼の噛み方: claim=名乗りを噛む(既定。依頼者: 占いか霊能の各候補以外は噛まれない)、grey=灰を噛む(11A のメモの前提。実際と違う)")
    p.add_argument("--seed", type=int, default=1, help="役職の配り方の乱数")
    p.set_defaults(func=playout)

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
