"""1試合を動かして、毎朝の盤面(昼1・昼2・昼3・昼4…)と、人狼の見込みを出す。

盤面整理は、昼1だけでなく、昼2・昼3・昼4でも続く。その日までに公開された情報(名乗り・占いの結果・霊能の報告・吊り・夜の死亡)に合う世界を
数え直して、人ごとの人狼の見込みを出し、「可能性の中でいちばん人狼らしい人」を吊る(依頼者: それが人狼ゲーム)。
ここでは、役職を無作為に配った1試合を、進行 policy(既定は尤度吊り)で動かして、朝ごとの盤面の報告を並べる。発言の「偽目」は、入れていない(盤面だけの読み)。
"""
from __future__ import annotations

import random

from .board import Board, board_report
from .progress import POLICY_NAME, POSTERIOR, prepare, play, sample_world


CO_KINDS = ("cat", "fakecat", "hunter", "fakehunter")                  # 吊りの指定に応じた名乗り(猫又・狩人のギドラと、対抗・偽のCO)


def _event_line(event: tuple, roles: dict[str, str]) -> str | None:
    kind, who, extra = event
    if kind == "hang":
        return f"吊り: {who}(正体: {roles[who]})"
    if kind == "takealong":
        return f"道連れ: {who}(正体: {roles[who]})"
    if kind == "bite":
        return f"夜の襲撃: {who}が死亡"
    if kind == "guard":
        return f"夜の襲撃: {who}を狙ったが、護衛が成功して、だれも死ななかった"
    if kind == "report":
        return f"霊能の報告: {who}は{extra}"
    if kind == "result":
        return f"占い {who} の結果: {extra[:-1]}は{extra[-1]}"
    if kind == "refuted":
        return f"{who}は、霊能の報告と食い違う結果を出した → 偽と分かった"
    if kind == "pp":
        return f"人外側が票をそろえた(PP): {who}"
    if kind == "rpp":
        return f"同数の抽選(RPP): 人外側の票は{who}、村の票は{extra}"
    if kind == "cat":
        return f"猫又CO: {who}({extra})"
    if kind == "fakecat":
        return f"猫又CO(偽): {who}({extra})"
    if kind == "hunter":
        return f"狩人CO: {who}({extra})"
    if kind == "fakehunter":
        return f"狩人CO(偽): {who}({extra})"
    return None                                                      # pick など、盤面の報告で足りるもの


def wolf_line(board: Board, wolf_p: dict[str, float]) -> str:
    """生きている人の、人狼の見込み(高い順)。"""
    ranked = sorted(board.alive, key=lambda p: (-wolf_p.get(p, 0.0), p))
    return "人狼の見込み(高い順): " + "、".join(f"{p} {wolf_p.get(p, 0.0) * 100:.0f}%" for p in ranked)


def playout_text(board: Board, policy: str = POSTERIOR, bite: str = "claim", seed: int = 1, roles: dict[str, str] | None = None, **play_kwargs) -> str:
    """盤面 board から、役職を無作為に配った1試合(roles を渡せば、その配役)を動かして、朝ごとの盤面と、吊りの流れを並べる。"""
    prep = prepare(board)
    if roles is None:
        roles, _ = sample_world(prep, random.Random(seed))
    trace: list = []
    lines: list[str] = []
    done = 0

    def emit(events: list) -> None:
        for event in events:
            text = _event_line(event, roles)
            if text:
                lines.append("  " + text)

    def flush() -> None:
        nonlocal done
        emit(trace[done:])
        done = len(trace)

    def observe(day: int, pb: Board, worlds: list, wolf_p: dict[str, float], target: str) -> None:
        nonlocal done
        new = trace[done:]
        cut = next((i for i, event in enumerate(new) if event[0] in CO_KINDS), len(new))
        emit(new[:cut])                                                      # 前の夜のできごと。この日の指定への名乗り(ギドラ・対抗)は、盤面のあとに出す
        done = len(trace)
        lines.append("")
        lines.append(board_report(pb, f"昼{day}の盤面"))
        if wolf_p:
            lines.append(wolf_line(pb, wolf_p))
        emit(new[cut:])
        if wolf_p:
            rank = 1 + sum(1 for p in pb.alive if wolf_p.get(p, 0.0) > wolf_p.get(target, 0.0) + 1e-9)
            lines.append(f"吊り先({POLICY_NAME.get(policy, policy)}): {target}(人狼の見込み {wolf_p.get(target, 0.0) * 100:.0f}%、高い方から {rank} 番目)")
        else:
            lines.append(f"吊り先({POLICY_NAME.get(policy, policy)}): {target}")

    won = play(prep, roles, policy, bite, random.Random(seed + 1), trace, observer=observe, **play_kwargs)
    flush()
    lines.append("")
    lines.append("== 結果: " + ("村の勝ち" if won else "人外の勝ち") + " ==")
    who = [f"{p}={roles[p]}" for p in sorted(roles) if p in board.players and p != board.dummy]
    if board.dummy:
        who.append(f"{board.dummy}={roles[board.dummy]}")
    lines.append("正体: " + " ".join(who))
    return "\n".join(lines).lstrip("\n")
