"""過去のゲームを途中まで再生して、ボットの出力と実際の発言を並べる(評価用)。

正規化済みのログ(logs/normalized/、git 管理外)を使う。話者の記号(A, B, C…)は、実在しない名前に置き換えて見せる。
ボットが再現する話者(me)の発言のうち、連投の先頭を切れ目にして、その直前までを卓の状況とし、
連投の中身(最大4件)を「実際の発言」とする。そのゲームの発言例は、プロンプトから除く(漏れを防ぐ)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from zinro_learn.parse import advance, EXTENSION

from .engine import make_context, user_message
from .prompt import as_text
from .transcript import Post, Table, _worth_noting
from .validate import build_turn

FAKE_NAMES = {"A": "アキラ", "B": "ブン", "C": "シン", "D": "ダイ", "E": "エイジ"}
LABEL = re.compile(r"《([A-Z]\d?)》")


def rename(text: str, names: dict[str, str]) -> str:
    return LABEL.sub(lambda m: names.get(m.group(1), m.group(1)), text)


def load_game(root: Path, game_id: str) -> dict:
    return json.loads((Path(root) / "logs/normalized" / f"{game_id}.json").read_text(encoding="utf-8"))


def table_from_game(game: dict, cut_seq: int, me: str, names: dict[str, str]) -> tuple[Table, dict[int, int]]:
    """cut_seq より前の出来事から、卓の状況を作る。戻り値の2つ目は、ログの seq → 発言番号。"""
    posts: list[Post] = []
    notes: list[tuple[int, str]] = []
    seqmap: dict[int, int] = {}
    phase, day, extensions = "setup", 0, 0
    for e in game["events"]:
        if e["seq"] >= cut_seq:
            break
        if e["kind"] == "speech":
            posts.append(Post(len(posts) + 1, names.get(e["speaker"], e["speaker"]), rename(e["text"], names)))
            seqmap[e["seq"]] = len(posts)
        elif e["kind"] == "system":
            phase, day = advance(phase, day, e["text"])
            if EXTENSION.search(e["text"]):
                extensions += 1
            if _worth_noting(e["text"]):
                notes.append((len(posts), e["text"].splitlines()[0]))
    role = game["players"][me]["role"]
    speakers = list(dict.fromkeys([names.get(me, me), *[p.speaker for p in posts]]))
    return Table(names.get(me, me), role, speakers, posts, notes, "day" if phase in ("setup", "day") else phase, extensions), seqmap


def burst_starts(game: dict, me: str) -> list[int]:
    """me の発言のうち、直前の発言が他人のもの(連投の先頭)の seq。"""
    starts, previous = [], None
    for e in game["events"]:
        if e["kind"] != "speech":
            continue
        if e["speaker"] == me and previous != me:
            starts.append(e["seq"])
        previous = e["speaker"]
    return starts


def truth_burst(game: dict, start_seq: int, me: str, names: dict[str, str], limit: int = 4) -> list[dict]:
    out = []
    for e in game["events"]:
        if e["seq"] < start_seq or e["kind"] != "speech":
            continue
        if e["speaker"] != me or len(out) == limit:
            break
        out.append({"game_seq": e["seq"], "text": rename(e["text"], names)})
    return out


def spread(items: list[int], k: int) -> list[int]:
    if k >= len(items):
        return items
    step = (len(items) - 1) / (k - 1) if k > 1 else 0
    return [items[round(i * step)] for i in range(k)]


def write_cases(root: Path, game_id: str, me: str, k: int, out: Path, register: str = "タメ口", min_before: int = 6) -> list[dict]:
    """評価用のケースを out に書く。in/ はモデルに見せるもの、truth/ は実際の発言(見せない)。"""
    root, out = Path(root), Path(out)
    game = load_game(root, game_id)
    names = dict(FAKE_NAMES)
    role = game["players"][me]["role"]
    system_path = out / "in" / f"{game_id}_{me}.system.txt"
    system_path.parent.mkdir(parents=True, exist_ok=True)
    (out / "truth").mkdir(parents=True, exist_ok=True)
    ctx = make_context(root, names.get(me, me), role, register, exclude_games=(game_id,))
    system_path.write_text(as_text(ctx.system), encoding="utf-8")
    cases = []
    speech_seqs = [e["seq"] for e in game["events"] if e["kind"] == "speech"]
    starts = [seq for seq in burst_starts(game, me) if speech_seqs.index(seq) >= min_before]
    for index, seq in enumerate(spread(starts, k), 1):
        table, seqmap = table_from_game(game, seq, me, names)
        name = f"{game_id}_{me}_{index:02d}"
        (out / "in" / f"{name}.user.txt").write_text(user_message(table, None, register), encoding="utf-8")
        truth = truth_burst(game, seq, me, names)
        meta = {
            "case": name, "game": game_id, "me": me, "fake_me": names.get(me, me), "role": role, "cut_seq": seq,
            "posts_before": len(table.posts), "system": system_path.name, "players": table.players,
            "truth": truth,
        }
        (out / "truth" / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        cases.append(meta)
    return cases


def tail(user_text: str, lines: int = 8) -> str:
    log = user_text.split("# ここまでの発言")[-1].split("\n# 機械的に拾った")[0].splitlines()[1:]
    return "\n".join(log[-lines:])


def score_case(root: Path, out: Path, meta: dict) -> str:
    """out/out/<case>.json(モデルの出力)を検査して、実際の発言と並べた文章にする。"""
    case = meta["case"]
    result_path = Path(out) / "out" / f"{case}.json"
    user_text = (Path(out) / "in" / f"{case}.user.txt").read_text(encoding="utf-8")
    head = [f"===== {case} ({meta['role']} / 切れ目 seq {meta['cut_seq']} / それまでの発言 {meta['posts_before']}件) =====", "[直前の流れ]", tail(user_text)]
    truth = ["[実際の発言]"] + [f"  ({t['game_seq']}) {t['text'].replace(chr(10), ' / ')}" for t in meta["truth"]]
    if not result_path.exists():
        return "\n".join([*head, *truth, "[ボット] (出力なし)"])
    data = json.loads(result_path.read_text(encoding="utf-8"))
    ctx = make_context(root, meta["fake_me"], meta["role"], exclude_games=(meta["game"],))
    turn = build_turn(
        data, me=meta["fake_me"], players=meta["players"], last_seq=meta["posts_before"],
        known_moves=ctx.known_moves, examples=ctx.examples,
    )
    bot = ["[ボット]"]
    for post in turn.posts:
        bot.append(f"  (→{post.reply_to} {','.join(post.moves)}) {post.text.replace(chr(10), ' / ')}")
    if not turn.posts:
        bot.append(f"  (投稿なし: {turn.silence})")
    bot += [f"  × {p}" for p in turn.problems] + [f"  ! {w}" for w in turn.warnings]
    bot.append(f"  読み: {turn.read.get('aim', '')}")
    chars = sum(len(p.text) for p in turn.posts)
    actual = sum(len(t["text"]) for t in meta["truth"])
    bot.append(f"  量: ボット {len(turn.posts)}件 {chars}字 / 実際 {len(meta['truth'])}件 {actual}字")
    return "\n".join([*head, *truth, *bot])
