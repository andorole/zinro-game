"""狩人が出るタイミングの比較(対になった比較)。

同じ試合を途中まで同じに進めて、狩人の判断の朝に二手に分ける:
- 出る側: その朝に狩人が名乗る(自発で昼 N の朝に出る、または場面で出る)。
- 潜伏側: そのまま(指定されたら出る=ギドラ)。
二手は、判断の朝まで同じ乱数・同じ状態なので、勝敗の差は、その判断の差だけ。判断の朝が来た試合(狩人が生きていて、まだ名乗っていない。
場面なら、その場面が起きた)だけを数える。依頼者の問い「出るタイミングで、どこが有効で、どこがギドラの方が良くて、どこでは指定されない限り
潜伏をするべきか」を、この計算の置き方で調べるための道具(依頼者の答えではなく、目安)。

比べ方:
- day: 指定されなくても、昼 N の朝に名乗る(自発)側と、指定されたときだけ名乗る側。
- scene: 場面(黒を出された朝・グレーが狭まって詰む朝・狼と狂が落ちて狩人ロラに持ち込める朝・GJのあとの朝)で名乗る側と、指定されたときだけ名乗る側。
  GJ は、GJのあとの朝すべてに出る側に倒して比べる(標準の割合 HUNTER_GJ_CO は小さいので、そのままだと試合が少ない)。
"""
from __future__ import annotations

import multiprocessing
import random
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from . import progress as P
from .board import Board

SCENES = ("黒", "詰み", "狩ロラ", "GJ")
MODES = ("day", "scene")
SCENE_NAME = {"黒": "黒を出された朝", "詰み": "詰む朝", "狩ロラ": "狩ロラの朝", "GJ": "GJのあとの朝"}


def _state(board: Board, roles: dict[str, str], trace: list, is_event) -> tuple[int, int]:
    """trace のうち is_event が真になるイベントの直前までの死者から、(生存者数, 生存の人狼数)。"""
    dead = {board.dummy} if board.dummy else set()
    for event in trace:
        if is_event(event):
            break
        if event[0] in ("hang", "bite", "takealong"):
            dead.add(event[1])
    alive = [p for p in board.players if p not in dead]
    return len(alive), sum(1 for p in alive if roles[p] == "人狼")


def _pairs(args) -> dict:
    board, policy, mode, arg, guard, cat, seed, indices = args
    prep = P.prepare(board)
    rows: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])      # (生存, 人狼) -> [試合数, 出る側の勝ち, 潜伏側の勝ち, 出る側だけ勝ち, 潜伏側だけ勝ち]
    split: dict[bool, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])                 # 占いが欠けている(ダミーが本物の占い)か -> 同じ並び
    common = dict(guard=guard, cat=cat, hunter="gidra")
    if mode == "day":
        alt_kw = dict(hunter_scenes=("指定",), hunter_day=arg)
        is_event = lambda t: t[0] == "hunter" and t[2] == "自発"
    else:
        alt_kw = dict(hunter_scenes=("指定", arg))
        is_event = lambda t, why=arg: t[0] == "hunter" and t[2] == why
    saved = P.HUNTER_GJ_CO
    if mode == "scene" and arg == "GJ":
        P.HUNTER_GJ_CO = 1.0
    try:
        for i in indices:
            base = seed * 1_000_003 + i
            roles, _ = P.sample_world(prep, random.Random(base * 2))
            trace: list = []
            alt = P.play(prep, roles, policy, "claim", random.Random(base * 2 + 1), trace, **common, **alt_kw)
            if not any(is_event(t) for t in trace):
                continue
            hidden = P.play(prep, roles, policy, "claim", random.Random(base * 2 + 1), None, hunter_scenes=("指定",), **common)
            for row in (rows[_state(board, roles, trace, is_event)], split[roles.get(board.dummy) == "占い師"]):
                row[0] += 1
                row[1] += alt
                row[2] += hidden
                row[3] += alt and not hidden
                row[4] += hidden and not alt
    finally:
        P.HUNTER_GJ_CO = saved
    return {k: list(v) for k, v in rows.items()}, {k: list(v) for k, v in split.items()}


def paired(board: Board, policy: str, mode: str, arg, n: int = 6000, guard: str | None = "env", cat: str = "gidra", seed: int = 1, workers: int = 1) -> dict:
    """mode が day なら、arg は昼の番号(自発で出る日)。scene なら、arg は場面(SCENES)。
    戻り値: {"games": 判断の朝が来た試合数, "alt": 出る側の勝ち, "base": 潜伏側の勝ち, "alt_only"・"base_only": 食い違った試合, "n": 全試合数,
             "rows": {(生存, 人狼): [試合数, 出る側の勝ち, 潜伏側の勝ち, 出る側だけ勝ち, 潜伏側だけ勝ち]},
             "split": {占いが欠けている(役欠けで、ダミーが本物の占い)か: 同じ並び}}"""
    if mode not in MODES:
        raise ValueError(f"知らない比べ方: {mode}")
    if mode == "day" and not (isinstance(arg, int) and arg >= 1):
        raise ValueError("day の arg は 1 以上の昼の番号")
    if mode == "scene" and arg not in SCENES:
        raise ValueError(f"知らない場面: {arg}")
    parts = [range(k, n, max(1, workers) * 4) for k in range(max(1, workers) * 4)]
    jobs = [(board, policy, mode, arg, guard, cat, seed, idx) for idx in parts]
    if workers <= 1:
        results = [_pairs(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork")) as pool:
            results = list(pool.map(_pairs, jobs))
    rows: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    split: dict[bool, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    for by_state, by_missing in results:
        for key, value in by_state.items():
            for j in range(5):
                rows[key][j] += value[j]
        for key, value in by_missing.items():
            for j in range(5):
                split[key][j] += value[j]
    return {"games": sum(v[0] for v in rows.values()), "alt": sum(v[1] for v in rows.values()), "base": sum(v[2] for v in rows.values()),
            "alt_only": sum(v[3] for v in rows.values()), "base_only": sum(v[4] for v in rows.values()), "n": n, "rows": {k: list(v) for k, v in rows.items()},
            "split": {k: list(v) for k, v in split.items()}}


def diff(result: dict) -> float | None:
    """出る側 − 潜伏側(勝率の差。判断の朝が来た試合がなければ None)。"""
    return (result["alt"] - result["base"]) / result["games"] if result["games"] else None


def split_result(result: dict, seer_missing: bool) -> dict:
    """占いが欠けている世界(役欠けで、ダミーが本物の占い)だけ、またはそうでない世界だけを取り出した結果(diff・stderr に渡せる形)。
    占いが欠けていると、占いの名乗りは全員偽なので、「ほかの占いの名乗りが全員偽と分かった=残る占いが本物」という決め打ちが外れる。"""
    games, alt, base, alt_only, base_only = result.get("split", {}).get(seer_missing, [0, 0, 0, 0, 0])
    return {"games": games, "alt": alt, "base": base, "alt_only": alt_only, "base_only": base_only, "n": result["n"], "rows": {}, "split": {}}


def stderr(result: dict) -> float | None:
    """対になった差の標準誤差: 食い違った試合(出る側だけ勝ち +1、潜伏側だけ勝ち −1)の平均の標準誤差。"""
    games = result["games"]
    if not games:
        return None
    mean = (result["alt_only"] - result["base_only"]) / games
    var = (result["alt_only"] + result["base_only"]) / games - mean ** 2
    return (var / games) ** 0.5


def timing_text(board: Board, title: str, policies, days=(1, 2, 3, 4), n: int = 6000, guard: str | None = "env", cat: str = "gidra", seed: int = 1, workers: int = 1,
                min_games: int = 100) -> str:
    """自発で出る日ごとの差と、場面ごとの差を、進行ごとに並べた表(点。出る側 − 潜伏側)。かっこ内は、その朝が来る試合の割合。"""
    def cell(result: dict, share: bool) -> str:
        d = diff(result)
        if d is None or result["games"] < min_games:
            return "—"
        return f"{d * 100:+.1f}" + (f"({result['games'] / result['n'] * 100:.0f}%)" if share else "")

    lines = [f"{title}(出る側 − 潜伏のまま=指定されたら出る。点。{n} 回ずつ。かっこ内は、その朝が来る試合の割合。—は {min_games} 試合未満)"]
    lines.append("  自発で出る日: " + " / ".join(f"昼{d}" for d in days) + "    場面: " + " / ".join(SCENE_NAME[s] for s in SCENES))
    for policy in policies:
        by_day = [cell(paired(board, policy, "day", d, n, guard, cat, seed, workers), False) for d in days]
        by_scene = [cell(paired(board, policy, "scene", s, n, guard, cat, seed, workers), True) for s in SCENES]
        lines.append(f"  {P.POLICY_NAME[policy]}: 自発 " + " / ".join(by_day) + " | 場面 " + " / ".join(by_scene))
    return "\n".join(lines)
