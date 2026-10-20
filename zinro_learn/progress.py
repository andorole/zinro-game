"""進行の比較: 占いロラ・グレランなどの進行ごとに、村の勝率を見積もる(試算)。

盤面(board.py)の世界の重みから、役職の割り当てを無作為に引く。そのうえで、村の進行(吊り方)と、狼の噛み方を決めて、
勝敗が付くまで日と夜を動かし、村が勝つ割合を数える。11A のメモ(`knowledge/prob_11a.md` の 2-3)と同じ型の、読みゼロの進行を比べる。

村の進行(毎日1人を吊る。霊能の結果は、翌朝に霊能が生きていれば出る):
- グレー: 毎日、名乗っていない人(灰)から無作為に吊る。灰がいなければ、占いの名乗りを吊る。
- 占いロラ: 占いの名乗りを、狼の見込みが高い順に吊る。ただし、いちばん狼の見込みが低い人(本物と見る人)は残す。そのあと灰。
- 黒スト: 占いの名乗りを同じ順に吊り、霊能の結果が黒(人狼)になったら、灰に切り替える。白が続くうちは、占いを吊る。
  最後の1人は、ほかの名乗りの全員が白と分かった(その人は人狼と決まる)ときだけ吊る。霊能の結果が出ないときは、最後の1人を残す。
- ロラ完遂: 占いの名乗りを、本物と見る人も含めて、すべて吊る。そのあと灰。
どの進行も、結果で黒を出された人(黒先)を、いちばん先に吊る。

狼の噛み方(毎晩1人):
- 灰: 灰(名乗っていない人)から無作為に噛む。11A のメモの基本の前提。
- 名乗り: 狼でない占い・霊能の名乗りを先に噛む(狼は、本物と狂人を見分けられないので、区別しない)。いなければ灰。

狩人の護衛(毎晩1人。狼がその人を噛もうとしたら、噛みは失敗する。狩人が生きているあいだだけ):
- なし: 護衛を入れない。
- 霊能: 霊能を護衛しつづける(霊護衛固定)。
- 黒出し: 結果で黒を出した占いの名乗りを護衛しつづける(黒出し占い護衛固定)。

占いの夜の結果(2日目以降。seer_results が真のとき):
- 占いの名乗りで生きている人は、毎晩1人を占い、翌朝、生きていれば結果を出す(夜に噛まれた占いは、結果を出せない)。相手は、灰から無作為。
- 本物は正しい色を出す。偽の人狼は、仲間に白を出し(身内切りは、戦術として強くないので、しない)、人狼でない人には、黒を出す
  重み FAKE_BLACK_LATER(白を出す場合を 1)で出す。偽の狂人は、相手が何であっても、同じ重みで黒を出す。
  依頼者の話「偽の二手目は、だいたい白」に合わせて、FAKE_BLACK_LATER は、初手の FAKE_BLACK_FIRST より小さい(仮)。
- 偽の人狼は、初手や次手で、仲間を囲う(仲間に白を出す)のが基本(依頼者の話)。次手(夜1の結果)では、灰の仲間の人狼がいれば、
  ENCLOSE_NEXT の割合で、その仲間に白を出す(仮)。初手の囲いは、盤面の重みには入れていない。
- 村は、「本物と見る占い」(狼の見込みがいちばん低い名乗り)の結果だけを信じる。黒は黒先として吊り、白を貰った人は、灰の無作為の吊りから外す。
  ほかの占いの結果は使わない。本物と見る占いが、実は偽なら、村はその嘘の結果に従う。

入れていないもの(大きなもの): 猫又、同数のときの票の操作(PP)、票が割れること、村の読み。
狂人は、人間として数える。人狼が人間と同数以上になれば、人狼の勝ち。人狼が全滅すれば、村の勝ち。
"""
from __future__ import annotations

import random
from bisect import bisect
from collections import defaultdict
from dataclasses import dataclass
from itertools import accumulate

from .board import Board, World, enumerate_worlds, marginals, pattern_label

FAKE_BLACK_LATER = 0.05          # 仮。偽の占いが、2日目以降の夜に、人狼でない人へ黒を出す重み(白を出す場合を 1)。初手(0.15)より小さい
ENCLOSE_NEXT = 0.5               # 仮。偽の人狼が、次手(夜1の結果)で、灰の仲間に白を出す(囲う)割合
POLICIES = ("grey", "roll_keep", "roll_stop", "roll")
POLICY_NAME = {"grey": "グレー", "roll_keep": "占いロラ", "roll_stop": "黒スト", "roll": "ロラ完遂"}
BITES = ("grey", "claim")
BITE_NAME = {"grey": "灰を噛む", "claim": "名乗りを噛む"}
GUARDS = (None, "medium", "blacksayer")
GUARD_NAME = {None: "護衛なし", "medium": "霊護衛固定", "blacksayer": "黒出し占い護衛固定"}


@dataclass
class Prepared:
    board: Board
    worlds: list[World]
    cumulative: list[float]
    free: list[str]                      # 灰(役職を個別に決めていない人)
    wolf_prob: dict[str, float]          # 人ごとの、人狼である見込み(世界の重みによる)
    seers: list[str]
    medium: str | None
    labels: list[str]                    # 世界ごとの、占いの名乗りの種類の組み合わせ(例: 真狼狂)


def prepare(board: Board) -> Prepared:
    mediums = board.claimants("霊能者")
    if len(mediums) > 1:
        raise ValueError("霊能の名乗りが2人以上の盤面は、まだ扱わない")
    worlds = enumerate_worlds(board)
    if not worlds:
        raise ValueError("この盤面に合う世界がない")
    keys = set(board.key_players())
    free = [p for p in board.players if p not in keys]
    marg = marginals(board, worlds)
    return Prepared(
        board=board,
        worlds=worlds,
        cumulative=list(accumulate(w.weight for w in worlds)),
        free=free,
        wolf_prob={p: marg[p].get("人狼", 0.0) for p in board.players},
        seers=board.claimants("占い師"),
        medium=mediums[0] if mediums else None,
        labels=[pattern_label(board, w.assign).split("-")[0] for w in worlds],
    )


def sample_world(prep: Prepared, rng: random.Random) -> tuple[dict[str, str], str]:
    """世界の重みに比例して1つ引き、灰に残りの役職を無作為に配る。(全員の役職, 占いの名乗りの種類の組み合わせ)"""
    i = bisect(prep.cumulative, rng.random() * prep.cumulative[-1])
    world = prep.worlds[min(i, len(prep.worlds) - 1)]
    roles = dict(world.assign)
    rest = [role for role, n in world.left.items() for _ in range(n)]
    rng.shuffle(rest)
    roles.update(zip(prep.free, rest))
    return roles, prep.labels[min(i, len(prep.worlds) - 1)]


def night_result(seer_role: str, target_role: str, rng: random.Random) -> str:
    """占いの名乗りが、夜に出す結果の色。本物は正しい色。偽の人狼は仲間に白、人狼でない人には黒を一定の重みで。偽の狂人は相手によらない。"""
    if seer_role == "占い師":
        return "黒" if target_role == "人狼" else "白"
    if seer_role == "人狼" and target_role == "人狼":
        return "白"
    black = FAKE_BLACK_LATER / (1 + FAKE_BLACK_LATER)        # 黒:白 = FAKE_BLACK_LATER : 1 の割合
    return "黒" if rng.random() < black else "白"


def play(prep: Prepared, roles: dict[str, str], policy: str, bite: str, rng: random.Random, trace: list | None = None,
         guard: str | None = None, seer_results: bool = True) -> bool:
    """1回の試合を動かす。村が勝てば True。trace があれば、(種類, 人, 色) の出来事を足す。"""
    board = prep.board
    black_sayer = next((r["player"] for r in board.results if r["kind"] == "占い" and r["color"] == "黒"), None)
    guarded = {None: None, "medium": prep.medium, "blacksayer": black_sayer}[guard]
    claimants = set(prep.seers) | ({prep.medium} if prep.medium else set())
    alive = set(board.players)
    for p in board.dead:                                  # 盤面にすでにある死者
        alive.discard(p)
    blacks = sorted({r["target"] for r in board.results if r["color"] == "黒" and r["target"] in alive}, key=lambda p: -prep.wolf_prob[p])
    order = sorted(prep.seers, key=lambda p: (-prep.wolf_prob[p], rng.random()))
    kept = order[-1] if order else None                   # 本物と見る占い(狼の見込みがいちばん低い名乗り)
    colors: dict[str, str] = {}                           # 霊能が報告した、吊られた人の色(公開)
    unreported: list[str] = []
    divined: dict[str, set[str]] = {s: set() for s in prep.seers}
    night = 0
    reports: list[tuple[str, str, str]] = []              # 夜に出た結果(占い, 相手, 色)。翌朝、占いが生きていれば出る
    safe: set[str] = set()                                # 本物と見る占いに白を出された人

    def counts() -> tuple[int, int]:
        wolves = sum(1 for p in alive if roles[p] == "人狼")
        return wolves, len(alive) - wolves

    while True:
        wolves, humans = counts()
        if wolves == 0:
            return True
        if wolves >= humans:
            return False
        if prep.medium in alive:                          # 朝: 霊能が生きていれば、前の吊りの色を報告する
            for t in unreported:
                colors[t] = "黒" if roles[t] == "人狼" else "白"
                if trace is not None:
                    trace.append(("report", t, colors[t]))
        unreported = []
        for seer, t, c in reports:                        # 朝: 夜に出た占いの結果。噛まれた占いは出せない
            if seer not in alive:
                continue
            if trace is not None:
                trace.append(("result", seer, t + c))
            if seer == kept:                              # 村は、本物と見る占いの結果だけを信じる
                if c == "黒" and t in alive and t not in blacks:
                    blacks.append(t)
                elif c == "白":
                    safe.add(t)
        reports = []
        all_greys = [p for p in alive if p not in claimants]
        greys = [p for p in all_greys if p not in safe] or all_greys      # 白を貰った灰は、無作為の吊りから外す
        alive_seers = [p for p in order if p in alive]
        hanged_seer_colors = [colors.get(p) for p in order if p not in alive]
        target = None
        alive_blacks = [p for p in blacks if p in alive]
        if alive_blacks:
            target = alive_blacks[0]                      # 黒先
        elif policy == "grey":
            target = rng.choice(sorted(greys)) if greys else None
        elif policy == "roll":
            target = alive_seers[0] if alive_seers else (rng.choice(sorted(greys)) if greys else None)
        elif policy == "roll_keep":
            rolling = [p for p in alive_seers if p != order[-1]]           # いちばん狼の見込みが低い人は残す
            target = rolling[0] if rolling else (rng.choice(sorted(greys)) if greys else None)
        elif policy == "roll_stop":
            others = [p for p in alive_seers if p != order[-1]]
            last_is_wolf = sum(1 for c in hanged_seer_colors if c == "白") == len(order) - 1 and order[-1] in alive_seers
            if "黒" in hanged_seer_colors:
                target = rng.choice(sorted(greys)) if greys else (alive_seers[0] if alive_seers else None)
            elif others:
                target = others[0]
            elif last_is_wolf:
                target = order[-1]                                          # ほかの名乗りが全員白なら、最後の1人は人狼と決まる
            else:
                target = rng.choice(sorted(greys)) if greys else (alive_seers[0] if alive_seers else None)
        else:
            raise ValueError(f"知らない進行: {policy}")
        if target is None:                                # 候補が尽きたとき: 占い、霊能、残る誰か
            rest = sorted(alive_seers) or sorted(alive)
            target = rng.choice(rest)
        alive.discard(target)
        unreported.append(target)
        if trace is not None:
            trace.append(("hang", target, "人狼" if roles[target] == "人狼" else "人間"))
        wolves, humans = counts()
        if wolves == 0:
            return True
        if wolves >= humans:
            return False
        # 夜: 狼が1人噛む
        nonwolf = sorted(p for p in alive if roles[p] != "人狼")
        if bite == "claim":
            pool = [p for p in nonwolf if p in claimants] or [p for p in nonwolf if p not in claimants]
        elif bite == "grey":
            pool = [p for p in nonwolf if p not in claimants] or nonwolf
        else:
            raise ValueError(f"知らない噛み方: {bite}")
        victim = rng.choice(pool)
        if guarded is not None and victim == guarded and any(roles[p] == "狩人" for p in alive):
            if trace is not None:
                trace.append(("guard", victim, ""))               # 護衛が成功して、だれも死なない
        else:
            alive.discard(victim)
            if trace is not None:
                trace.append(("bite", victim, ""))
        night += 1
        if seer_results:                                          # 夜に、生きている占いの名乗りが占う
            for seer in prep.seers:
                if seer not in alive:
                    continue
                options = [p for p in sorted(alive) if p != seer and p not in divined[seer]]
                options = [p for p in options if p not in claimants] or options
                mates = [p for p in options if roles[p] == "人狼"]
                if night == 1 and roles[seer] == "人狼" and mates and rng.random() < ENCLOSE_NEXT:
                    t = rng.choice(mates)                          # 次手で、灰の仲間を囲う
                    divined[seer].add(t)
                    reports.append((seer, t, "白"))
                elif options:
                    t = rng.choice(options)
                    divined[seer].add(t)
                    reports.append((seer, t, night_result(roles[seer], roles[t], rng)))


def win_rate(board: Board, policy: str, bite: str = "grey", n: int = 20000, seed: int = 1, prep: Prepared | None = None,
             guard: str | None = None, seer_results: bool = True) -> dict:
    """進行 policy・噛み方 bite で n 回動かした、村の勝率。構成(占いの名乗りの種類の組み合わせ)別の割合も返す。"""
    prep = prep or prepare(board)
    world_rng, play_rng = random.Random(seed), random.Random(seed + 1)   # 世界の引きは、進行によらず同じ列にする(比べやすい)
    wins, total = 0, defaultdict(int)
    by_win: dict[str, int] = defaultdict(int)
    for _ in range(n):
        roles, label = sample_world(prep, world_rng)
        total[label] += 1
        if play(prep, roles, policy, bite, play_rng, guard=guard, seer_results=seer_results):
            wins += 1
            by_win[label] += 1
    rate = wins / n
    return {
        "rate": rate,
        "stderr": (rate * (1 - rate) / n) ** 0.5,
        "by_label": {k: {"share": total[k] / n, "rate": by_win[k] / total[k]} for k in sorted(total, key=lambda k: -total[k])},
    }


def compare(board: Board, n: int = 20000, seed: int = 1, policies=POLICIES, bites=BITES, guard: str | None = None,
            seer_results: bool = True) -> dict:
    """進行 × 噛み方の、村の勝率の表。{(bite, policy): win_rate の結果}。同じ世界の引きで比べる(seed を共通にする)。"""
    prep = prepare(board)
    return {(b, p): win_rate(board, p, b, n, seed, prep, guard, seer_results) for b in bites for p in policies}


def hit_rates(board: Board) -> dict:
    """昼1の1本目の吊りで、人狼に当たる見込み: 占いの名乗りの人ごと、灰の1人、霊能。世界の重みによる(厳密)。"""
    prep = prepare(board)
    claimants = set(prep.seers) | ({prep.medium} if prep.medium else set())
    greys = [p for p in board.alive if p not in claimants]
    return {
        "占い": {p: prep.wolf_prob[p] for p in prep.seers},
        "灰": sum(prep.wolf_prob[p] for p in greys) / len(greys) if greys else 0.0,
        "霊能": prep.wolf_prob[prep.medium] if prep.medium else 0.0,
        "灰の人数": len(greys),
    }


def compare_text(board: Board, title: str, n: int = 20000, seed: int = 1, guard: str | None = None, seer_results: bool = True) -> str:
    table = compare(board, n, seed, guard=guard, seer_results=seer_results)
    first = next(iter(table.values()))
    labels = list(first["by_label"])                      # 構成の割合の大きい順(どの進行でも、世界の引きは同じ)
    lines = [f"{title}(試算 {n} 回。誤差は ±{max(r['stderr'] for r in table.values()) * 100:.1f}% くらい)"]
    lines.append("構成の割合: " + "、".join(f"{k} {first['by_label'][k]['share'] * 100:.0f}%" for k in labels))
    for bite in BITES:
        parts = []
        for policy in POLICIES:
            r = table[(bite, policy)]
            detail = " / ".join(f"{k} {r['by_label'][k]['rate'] * 100:.0f}%" for k in labels[:2])
            parts.append(f"{POLICY_NAME[policy]} {r['rate'] * 100:.1f}%({detail})")
        lines.append(f"  {BITE_NAME[bite]}: " + " | ".join(parts))
    return "\n".join(lines)
