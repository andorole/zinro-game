"""使い方:
  python -m zinro_bot prompt --role 村人 --me 名前 --format chat   # システムプロンプトを出す(Claude のプロジェクトに貼る用)
  python -m zinro_bot check 出力.json --log ログ.txt --me 名前       # 出力(JSON)を、貼れるか検査する(API を使わない経路用)
  python -m zinro_bot reply ログ.txt --me 名前 --role 人狼    # 貼ったログを読んで、次の発言の案を出す(要 ANTHROPIC_API_KEY)
  pbpaste | python -m zinro_bot reply - --me 名前             # 標準入力から読む
  python -m zinro_bot chat --me ボット --role 村人 --players あなた,相手   # 手元で会話して試す
  python -m zinro_bot cases --game log08 --me B --out eval    # 評価用のケースを作る(過去ログを途中まで再生)
  python -m zinro_bot score eval                              # eval/out/ の出力を、実際の発言と並べる
zinro.net には接続しない。投稿は人間が行う。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import Result, make_context, make_memory, respond
from .llm import AnthropicClient, ApiError, ScriptedClient, load_env
from .prompt import as_text, build_system
from .replay import score_case, write_cases
from .transcript import Table, parse_table, render
from .validate import build_turn


def split_names(value: str) -> list[str]:
    return [name.strip() for name in value.split(",") if name.strip()]


def demo_reply(table: Table) -> dict:
    """--fake 用の定型応答。モデルは呼ばない(流れの動作確認だけ)。"""
    if not table.posts:
        posts = [{"reply_to": [], "moves": ["greet"], "text": "おはよう"}]
    else:
        last = table.posts[-1]
        posts = [{"reply_to": [last.seq], "moves": ["probe"], "text": f"{last.speaker}は、どういう根拠でそう思うの？"}]
    return {"read": {"players": {}, "pending": [], "swing": "", "aim": "(--fake: 動作確認用の定型応答)"}, "posts": posts, "vote": None, "silence": ""}


def make_client(args, table: Table):
    if args.fake:
        return ScriptedClient([demo_reply(table) for _ in range(args.retries + 1)])
    return AnthropicClient(model=args.model, thinking_budget=args.thinking)


def format_result(result: Result, plain: bool = False) -> str:
    turn = result.turn
    if plain:
        return "\n---\n".join(post.text for post in turn.posts)
    out: list[str] = []
    read = turn.read
    if read:
        out.append("■ 読み(チャットには貼らない)")
        if read.get("aim"):
            out.append(f"  狙い: {read['aim']}")
        for name, note in (read.get("players") or {}).items():
            out.append(f"  {name}: {note}")
        for item in read.get("pending") or []:
            out.append(f"  未回収: {item}")
        if read.get("swing"):
            out.append(f"  第三者: {read['swing']}")
        out.append("")
    if turn.posts:
        out.append("■ 投稿案(上から順に貼る)")
        for index, post in enumerate(turn.posts, 1):
            tags = ",".join(post.moves)
            target = "返信先なし" if not post.reply_to else "返信先 " + " ".join(f"#{n}" for n in post.reply_to)
            out.append(f"[{index}] ({target}{' / ' + tags if tags else ''})")
            out.append(post.text)
            out.append("")
    else:
        out.append(f"■ 今は書かない: {turn.silence or '(検査で全部落ちた)'}")
    if turn.vote:
        out.append(f"■ 投票先: {turn.vote}")
    for problem in turn.problems:
        out.append(f"× 捨てた投稿: {problem}")
    for warning in turn.warnings:
        out.append(f"! {warning}")
    for post in turn.posts:
        for warning in post.warnings:
            out.append(f"! {warning}")
    return "\n".join(out).rstrip()


def usage_line(result: Result) -> str:
    total = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    for usage in result.usage:
        for key in total:
            total[key] += usage.get(key, 0) or 0
    return f"(試行{result.attempts}回 / 入力{total['input_tokens']} 出力{total['output_tokens']} キャッシュ読込{total['cache_read_input_tokens']} 書込{total['cache_creation_input_tokens']})"


def load_memory(root: Path, name: str | None) -> dict | None:
    if not name:
        return None
    path = root / "logs/sessions" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def save_memory(root: Path, name: str | None, table: Table, result: Result) -> None:
    if not name:
        return
    path = root / "logs/sessions" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(make_memory(table, result.turn), ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_prompt(args) -> None:
    blocks = build_system(Path(args.root), args.me, args.role, args.register, tuple(args.exclude_game), output_format=args.format)
    text = as_text(blocks)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{args.out}: {len(text)}字")
    else:
        print(text)


def cmd_reply(args) -> None:
    root = Path(args.root)
    load_env(root)
    text = sys.stdin.read() if args.log == "-" else Path(args.log).read_text(encoding="utf-8")
    table = parse_table(text, me=args.me, role=args.role, players=split_names(args.players), order=args.order)
    for warning in table.warnings:
        print(f"警告: {warning}", file=sys.stderr)
    if args.show_transcript:
        print(render(table, args.remaining, args.register))
        return
    ctx = make_context(root, table.me, table.role, args.register, tuple(args.exclude_game))
    if args.dry_run:
        print(f"システムプロンプト: {sum(len(b['text']) for b in ctx.system)}字 / 発言{len(table.posts)}件 / 自分: {table.me} ({table.role}) / 局面: {table.phase}")
        return
    try:
        result = respond(make_client(args, table), ctx, table, args.remaining, args.register, args.retries, load_memory(root, args.session))
    except ApiError as exc:
        raise SystemExit(f"エラー: {exc}") from exc
    save_memory(root, args.session, table, result)
    if args.json:
        turn = result.turn
        print(json.dumps({"posts": [{"reply_to": p.reply_to, "moves": p.moves, "text": p.text} for p in turn.posts], "vote": turn.vote, "silence": turn.silence, "read": turn.read}, ensure_ascii=False, indent=1))
    else:
        print(format_result(result, args.plain))
        if not args.plain:
            print(usage_line(result), file=sys.stderr)


def cmd_check(args) -> None:
    """モデルが出した JSON(出力形式)を、貼れるかどうか検査する。API を使わない経路(Claude Code など)用。"""
    root = Path(args.root)
    raw = sys.stdin.read() if args.turn == "-" else Path(args.turn).read_text(encoding="utf-8")
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start : end + 1])
    table = parse_table(Path(args.log).read_text(encoding="utf-8"), me=args.me, role=args.role, players=split_names(args.players), order=args.order)
    ctx = make_context(root, table.me, table.role, args.register)
    turn = build_turn(data, me=table.me, players=table.players, last_seq=table.last_seq(), known_moves=ctx.known_moves, examples=ctx.examples)
    print(format_result(Result(turn)))
    if turn.problems:
        raise SystemExit(1)


def cmd_chat(args) -> None:
    root = Path(args.root)
    load_env(root)
    players = split_names(args.players) or ["あなた"]
    lines = ["鯖: 恐ろしい夜が明け、朝になりました。"]
    ctx = make_context(root, args.me, args.role, args.register)
    print(f"{args.me}({args.role})と会話する。「名前: 発言」で別の人として発言。空行か /go でボットの番。/log で履歴、/quit で終了。")
    memory = None
    while True:
        try:
            line = input("> ").rstrip()
        except EOFError:
            return
        if line == "/quit":
            return
        if line == "/log":
            print(render(parse_table("\n".join(lines), args.me, args.role, players + [args.me], "oldest-first"), None, args.register))
            continue
        if line and line != "/go":
            speaker = line.split(":", 1)[0].strip() if ":" in line else ""
            lines.append(line if speaker in players else f"{players[0]}: {line}")
            continue
        table = parse_table("\n".join(lines), args.me, args.role, players + [args.me], "oldest-first")
        try:
            result = respond(make_client(args, table), ctx, table, None, args.register, args.retries, memory)
        except ApiError as exc:
            print(f"エラー: {exc}")
            continue
        memory = make_memory(table, result.turn)
        print(format_result(result))
        for post in result.turn.posts:
            first, *rest = post.text.split("\n")
            lines += [f"{args.me}: {first}", *rest]


def cmd_cases(args) -> None:
    cases = write_cases(Path(args.root), args.game, args.me, args.k, Path(args.out), args.register, args.min_before)
    for meta in cases:
        print(f"{meta['case']}: 切れ目 seq {meta['cut_seq']}、それまでの発言 {meta['posts_before']}件、実際の発言 {len(meta['truth'])}件")
    print(f"{args.out}/in/ のファイルをモデルに見せ、出力を {args.out}/out/<ケース名>.json に置いてから score を実行する")


def cmd_score(args) -> None:
    out = Path(args.dir)
    for path in sorted((out / "truth").glob("*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        print(score_case(Path(args.root), out, meta))
        print()


def add_model_options(p) -> None:
    p.add_argument("--model", help="モデル名(省略時は環境変数 ZINRO_BOT_MODEL、なければ既定)")
    p.add_argument("--thinking", type=int, help="考えさせるトークン数の上限(指定すると、tool の強制をやめて考えさせる)")
    p.add_argument("--fake", action="store_true", help="モデルを呼ばず、定型応答で流れだけ確認する")
    p.add_argument("--retries", type=int, default=2, help="検査に落ちたとき、出し直させる回数")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="zinro_bot")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prompt", help="システムプロンプトを出す")
    p.add_argument("--me")
    p.add_argument("--role", choices=["村人", "人狼"])
    p.add_argument("--register", choices=["タメ口", "敬語"], default="タメ口")
    p.add_argument("--exclude-game", action="append", default=[], help="このゲームの発言例を除く(評価用)")
    p.add_argument("--format", choices=["json", "chat"], default="json", help="chat は、Claude のチャットやプロジェクトに貼って、読める形で返させる用")
    p.add_argument("--out")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("check", help="出力(JSON)を、貼れるかどうか検査する")
    p.add_argument("turn", help="JSON のファイル。- なら標準入力")
    p.add_argument("--log", required=True, help="元のログ")
    p.add_argument("--me")
    p.add_argument("--role", choices=["村人", "人狼"])
    p.add_argument("--players", default="")
    p.add_argument("--order", choices=["auto", "newest-first", "oldest-first"], default="auto")
    p.add_argument("--register", choices=["タメ口", "敬語"], default="タメ口")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("reply", help="貼ったログを読んで、次の発言の案を出す")
    p.add_argument("log", help="ログのファイル。- なら標準入力")
    p.add_argument("--me", help="自分の名前(役職通知が1人分だけなら省略できる)")
    p.add_argument("--role", choices=["村人", "人狼"])
    p.add_argument("--players", default="", help="発言者の名前をコンマ区切りで(自動判定が合わないとき)")
    p.add_argument("--order", choices=["auto", "newest-first", "oldest-first"], default="auto")
    p.add_argument("--remaining", type=int, help="残り時間(秒)")
    p.add_argument("--register", choices=["タメ口", "敬語"], default="タメ口")
    p.add_argument("--exclude-game", action="append", default=[])
    p.add_argument("--session", help="セッション名。指定すると、前回の読み(狙い・投票先の見込みなど)を logs/sessions/ に残し、次回の入力に添える")
    p.add_argument("--show-transcript", action="store_true", help="読み取った卓の状況を出して終わる(名前や並びの確認用)")
    p.add_argument("--dry-run", action="store_true", help="プロンプトの大きさだけ出して終わる")
    p.add_argument("--plain", action="store_true", help="投稿だけを出す(複数は --- で区切る)")
    p.add_argument("--json", action="store_true")
    add_model_options(p)
    p.set_defaults(func=cmd_reply)

    p = sub.add_parser("chat", help="手元で会話して試す")
    p.add_argument("--me", required=True)
    p.add_argument("--role", choices=["村人", "人狼"], required=True)
    p.add_argument("--players", default="あなた", help="他の参加者の名前(コンマ区切り)")
    p.add_argument("--register", choices=["タメ口", "敬語"], default="タメ口")
    add_model_options(p)
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("cases", help="評価用のケースを作る")
    p.add_argument("--game", required=True)
    p.add_argument("--me", required=True, help="再現する話者の記号(B, A など)")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--min-before", type=int, default=6, help="切れ目の前に、この件数以上の発言があるものだけ使う(0なら序盤も)")
    p.add_argument("--out", default="eval")
    p.add_argument("--register", choices=["タメ口", "敬語"], default="タメ口")
    p.set_defaults(func=cmd_cases)

    p = sub.add_parser("score", help="出力を実際の発言と並べる")
    p.add_argument("dir")
    p.set_defaults(func=cmd_score)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
