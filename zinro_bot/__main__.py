"""使い方:
  python -m zinro_bot prompt --role 村人 --me 名前 --format chat   # システムプロンプトを出す(Claude のプロジェクトに貼る用)
  python -m zinro_bot check 出力.json --log ログ.txt --me 名前       # 出力(JSON)を、貼れるか検査する(API を使わない経路用)
  python -m zinro_bot reply ログ.txt --me 名前 --role 人狼    # 貼ったログを読んで、次の発言の案を出す(要 ANTHROPIC_API_KEY)
  pbpaste | python -m zinro_bot reply - --me 名前             # 標準入力から読む
  python -m zinro_bot chat --me ボット --role 村人 --players あなた,相手   # 手元で会話して試す(所要秒つき)
  python -m zinro_bot room --out room.html                    # 練習部屋(ブラウザ)のページを作る。Claude の Artifact として開くと、キーなしで会話できる
  python -m zinro_bot eval --game log08:A --game log10:B --k 3   # 過去ゲームを途中まで再生して、モデルに回し、実際の発言と並べる(所要秒・票の集計つき)
  python -m zinro_bot cases --game log08 --me B --out eval    # 評価用のケースだけ作る(出力は別のモデルや人が置く場合)
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
from .replay import run_cases, score_case, summarize, write_cases
from .room import build_room
from .transcript import Table, parse_table, render
from .validate import build_turn, turn_to_dict


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
    return f"(所要{result.seconds:.1f}秒 / 試行{result.attempts}回 / 入力{total['input_tokens']} 出力{total['output_tokens']} キャッシュ読込{total['cache_read_input_tokens']} 書込{total['cache_creation_input_tokens']})"


def session_summary(results: list[Result]) -> str:
    """chat の終了時に出す、ターンごとの所要時間と量の集計。"""
    if not results:
        return ""
    seconds = [r.seconds for r in results]
    posts = sum(len(r.turn.posts) for r in results)
    chars = sum(len(p.text) for r in results for p in r.turn.posts)
    turns = len(results)
    return (
        f"集計: {turns}ターン / 所要 平均{sum(seconds) / turns:.1f}秒 最大{max(seconds):.1f}秒 / "
        f"投稿 計{posts}件{chars}字(1ターン平均 {posts / turns:.1f}件 {chars / turns:.0f}字)"
    )


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
        result = respond(make_client(args, table), ctx, table, args.remaining, args.register, args.retries, load_memory(root, args.session), args.critic)
    except ApiError as exc:
        raise SystemExit(f"エラー: {exc}") from exc
    save_memory(root, args.session, table, result)
    if args.json:
        print(json.dumps(turn_to_dict(result.turn), ensure_ascii=False, indent=1))
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
    print(f"{args.me}({args.role})と会話する。「名前: 発言」で別の人として発言。空行か /go でボットの番。")
    print("/残り 秒(残り時間を伝える)  /延長  /投票(投票時間にする)  /log(履歴)  /quit(終了。所要時間の集計を出す)")
    memory, remaining, results = None, None, []
    while True:
        try:
            line = input("> ").rstrip()
        except EOFError:
            break
        if line == "/quit":
            break
        if line == "/log":
            print(render(parse_table("\n".join(lines), args.me, args.role, players + [args.me], "oldest-first"), remaining, args.register))
            continue
        if line.startswith("/残り"):
            value = line[len("/残り"):].strip()
            remaining = int(value) if value.isdigit() else None
            print(f"残り時間: {remaining}秒" if remaining is not None else "残り時間: 指定なし")
            continue
        if line == "/延長":
            lines.append("鯖: 時間を90秒延長しました")
            continue
        if line == "/投票":
            lines.append("鯖: 投票時間になりました。話すのをやめてください。")
            continue
        if line and line != "/go":
            speaker = line.split(":", 1)[0].strip() if ":" in line else ""
            lines.append(line if speaker in players else f"{players[0]}: {line}")
            continue
        table = parse_table("\n".join(lines), args.me, args.role, players + [args.me], "oldest-first")
        try:
            result = respond(make_client(args, table), ctx, table, remaining, args.register, args.retries, memory, args.critic)
        except ApiError as exc:
            print(f"エラー: {exc}")
            continue
        memory = make_memory(table, result.turn)
        results.append(result)
        print(format_result(result))
        print(usage_line(result))
        for post in result.turn.posts:
            first, *rest = post.text.split("\n")
            lines += [f"{args.me}: {first}", *rest]
    summary = session_summary(results)
    if summary:
        print(summary)


def cmd_cases(args) -> None:
    cases = write_cases(Path(args.root), args.game, args.me, args.k, Path(args.out), args.register, args.min_before)
    for meta in cases:
        print(f"{meta['case']}: 切れ目 seq {meta['cut_seq']}、それまでの発言 {meta['posts_before']}件、実際の発言 {len(meta['truth'])}件")
    print(f"{args.out}/in/ のファイルをモデルに見せ、出力を {args.out}/out/<ケース名>.json に置いてから score を実行する")


def cmd_room(args) -> None:
    html = build_room(Path(args.root))
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"{args.out}: {len(html)}字")


def cmd_eval(args) -> None:
    """過去ゲームを途中まで再生してモデルに回し、実際の発言と並べる。--game は、ゲーム名:話者(例 log08:A)で何度でも指定できる。"""
    root, out = Path(args.root), Path(args.out)
    load_env(root)
    metas: list[dict] = []
    for spec in args.game:
        game_id, _, me = spec.partition(":")
        me = me or args.me
        if not me:
            raise SystemExit(f"{spec}: 再現する話者を指定する(--me、または {spec}:B のように書く)")
        metas += run_cases(root, game_id, me, args.k, out, lambda table: make_client(args, table), args.register, args.min_before, args.retries, args.critic)
    errors = [meta["error"] for meta in metas if meta.get("error")]
    if metas and len(errors) == len(metas):
        raise SystemExit(f"エラー: {errors[0]}")
    for meta in metas:
        print(score_case(root, out, meta))
        if meta.get("error"):
            print(f"  × API エラー: {meta['error']}")
        print()
    print(summarize(out, metas))
    print(f"(出力と所要時間は {out}/out/ に残してある。実際の発言は {out}/truth/ にあり、モデルには見せていない)")


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
    p.add_argument("--critic", action="store_true", help="通った案を、もう一度点検させる(呼び出しが1回増える。取り違え・矛盾・繰り返しを減らす)")


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

    p = sub.add_parser("room", help="練習部屋(ブラウザで動くページ)を作る")
    p.add_argument("--out", default="room.html")
    p.set_defaults(func=cmd_room)

    p = sub.add_parser("eval", help="過去ゲームを途中まで再生してモデルに回し、実際の発言と並べる(所要時間・票の集計つき)")
    p.add_argument("--game", action="append", required=True, help="ゲーム名:再現する話者の記号(例 log08:A)。何度でも指定できる")
    p.add_argument("--me", help="--game に話者を書かなかったときの話者")
    p.add_argument("--k", type=int, default=3, help="1ゲームあたりのケース数")
    p.add_argument("--min-before", type=int, default=6, help="切れ目の前に、この件数以上の発言があるものだけ使う(0なら序盤も)")
    p.add_argument("--out", default="eval")
    p.add_argument("--register", choices=["タメ口", "敬語"], default="タメ口")
    add_model_options(p)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("score", help="出力を実際の発言と並べる")
    p.add_argument("dir")
    p.set_defaults(func=cmd_score)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
