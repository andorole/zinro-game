"""盤面整理: 公開されている情報に合う、役職の割り当て(世界)を数える。

初心者が盤面整理から始めるのと同じ手順を、機械でたどれるようにする。
- 入力は、名乗り(CO)・占い/霊能の結果・処刑・夜の死亡・狼CO(公開されたものだけ)。実際の役職は使わない。
- 出力は、その情報に合う世界の一覧(名乗りの「真・狼・狂」の組み合わせ)、定番かどうかの段階、確定した黒・白、
  縄の数(外せる吊りの回数)。
- 「定番」の段階は、依頼者に聞いた環境(現在の12A猫: 占い2・霊能1なら、占いは真と狼、霊は真が定番。占い3・霊能1なら、
  真狂狼が多く、真狼狼もありうる。霊はたいてい真)を、規則にしたもの(world_judgement)。実戦の比率ではなく、
  「定番／ありうる／まれ」の目安。重みの数字は仮。
- 占い・霊能の本物は、一発言目に名乗る(ロケットCO。RCO)。狐のない配役では、ロケットCOが強いので、決まりというより約束事として、
  潜伏は「ない」(依頼者の説明)。Board.rco が真なら、名乗りに本物がいない世界(潜伏)は、世界から外す。
- 結果の出し方の癖も、環境の話から入れた(result_factor)。初手に偽の占いが、人狼でない人へ黒を出すのは「人外の凸」で、
  最良手ではないので少ない。だから、初手の黒(対抗黒・グレーへの黒)は、真目になる(3-1 の対抗黒は、結構真目)。初手の対抗白は、本物が出せる相手が
  狂人だけ(相手が人狼なら黒になる)なので、出した側は偽目。いちばん有利な真狂狼でも、8割は偽(11A のメモの数え方と同じ)。
  数字は仮で、依頼者に確かめる。

世界の数え方: 名乗った人・結果の対象・死者・狼COの人(主要な人)の役職を、役職の人数の範囲で総当たりし、
結果の真偽の条件(本物の占い師・霊能者の結果は正しい)を満たすものを残す。ほかの人(灰)は、残った役職を
どう配ってもよい(同じ扱い)ので、配り方の数と確率だけを数える。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from math import factorial
from pathlib import Path

# 12A猫の役職の人数。ダミー(初日犠牲者。村人)を除く11人ぶん。
ROLES_12A_NEKO = {"人狼": 3, "狂人": 1, "占い師": 1, "霊能者": 1, "狩人": 1, "猫又": 1, "村人": 3}
# 11A・10A狩の役職の人数。ダミー(初日犠牲者)が村人のときの、参加者ぶん。依頼者の話: 比較的簡単な配役。頭数にダミーを1人と数えて、11A は人狼2・占い1・狩人1・
# 霊能1・狂人1・村人5(`prob_11a.md`)、10A狩は村人4(依頼者の訂正)。役欠けありでは、ダミーの分の村人を1枚足した山から、ダミーが人狼以外の1枚を持つ(make_board)。
ROLES_11A = {"人狼": 2, "狂人": 1, "占い師": 1, "霊能者": 1, "狩人": 1, "村人": 4}
ROLES_10A_KARI = {"人狼": 2, "狂人": 1, "占い師": 1, "霊能者": 1, "狩人": 1, "村人": 3}
DUMMY = "ダミー"                                         # 初日犠牲者(役欠けありのとき、役職は人狼以外のどれか)
CLAIM_ROLES = ("占い師", "霊能者")                       # 名乗られる役職(結果を出す役職)
ROLE_OF_KIND = {"占い": "占い師", "霊能": "霊能者"}
TIER_NAME = {3: "定番", 2: "ありうる", 1: "まれ"}
# 仮の重み(世界1通りあたり)。「定番」を数にしただけで、実戦の比率ではない。まれは、切り・偶然(偽の黒が人狼に当たる)と、
# rco でないときの潜伏(本物が名乗らない)。潜伏は、配り方の数が多いので、1通りの重みを小さくした。
TIER_WEIGHT = {3: 1.0, 2: 0.2, 1: 0.005}
# ありうるのうち、偽が2人以上で人狼だけの世界(3-1 の真狼狼)は、1通りの重みを別にした。依頼者の数字は「3-1 は真狂狼 7.5 : 真狼狼 2.5」。
# 3-1 の通り数は、真狂狼も真狼狼も2520通りなので、真狼狼の重みは 1/3(2-1 の真狂の 0.2 は、「いまの置き方でよい」ので動かさない)。
WEIGHT_NO_MAD = 1 / 3
# 偽の占いが、初手に「人狼でない人」へ黒を出す重み(白を出す場合を 1 としたときの比)。依頼者は「1割よりはある。2割程度」と言い、
# そのあと、3-1 の対抗黒を護衛固定の目安(7割台)に寄せるため、「1.5割にしよう。真狼狼を2.5にすれば丁度良さそう」と決めた。
FAKE_BLACK_FIRST = 0.15
# 白ランオン(人狼online。依頼者: 10A狩・11A は、基本的に初日に白が出る環境でやる): 本物の占い師の初日(夜0)の結果は、人狼でない人への無作為な白で、黒は出ない。
# だから、初手に黒を出す占いは、その場で偽と分かる。偽の占いがそれでも初手に黒を出すのは、ランオフ(0.15)より少ない(仮。確認したい)。
FAKE_BLACK_FIRST_RANDOM_WHITE = 0.05
TYPE_ORDER = "真狼狂"                                    # 名乗りの種類: 本物・人狼・狂人


@dataclass(frozen=True)
class Setup:
    """配役と、その環境の約束事。"""

    key: str
    name: str
    roles: dict[str, int]                                # ダミーが村人のときの、参加者ぶん
    random_white: bool                                   # 白ランオン(本物の占い師の初日の結果は、無作為な白)
    fake_black_first: float                              # 偽の占いが、初手に人狼でない人へ黒を出す重み
    missing: bool = False                                # 役欠けあり(ダミーの役職は、人狼以外のどれかで、欠けうる)


# 12A猫は、役欠けなしのまま(log17 の部屋の「役欠け:あり」の意味は、確認したい)。10A狩・11A は、役欠けあり(依頼者: 人狼以外の全てが欠けうる)。
SETUPS = {
    "12a-neko": Setup("12a-neko", "12A猫", ROLES_12A_NEKO, False, FAKE_BLACK_FIRST, False),
    "11a": Setup("11a", "11A", ROLES_11A, True, FAKE_BLACK_FIRST_RANDOM_WHITE, True),
    "10a-kari": Setup("10a-kari", "10A狩", ROLES_10A_KARI, True, FAKE_BLACK_FIRST_RANDOM_WHITE, True),
}
DEFAULT_SETUP = "12a-neko"


@dataclass
class Board:
    """ある時点で公開されている情報。"""

    players: list[str]                                   # 参加者(役欠けありのときは、ダミーも入れる)
    roles: dict[str, int]                                # 役職の山(役欠けありのときは、ダミーの分も入れる)
    claims: list[tuple[str, str]] = field(default_factory=list)          # (名乗った人, 役職)
    results: list[dict] = field(default_factory=list)                    # kind(占い/霊能)・player・target・color(黒/白)・first(その人の初手の結果か)
    executed: list[str] = field(default_factory=list)
    bitten: list[str] = field(default_factory=list)                      # 夜の襲撃で死んだ人
    other_dead: list[str] = field(default_factory=list)                  # 道連れなど、襲撃でない死
    wolf_co: list[str] = field(default_factory=list)                     # 「狼CO」した人
    ongoing: bool = True                                                 # まだ勝敗が決まっていない(人狼が全滅しておらず、人間より少ない)
    rco: bool = False                                                    # 占い・霊能の本物は、一発言目に名乗る(ロケットCO)。名乗りに本物がいない(潜伏)世界は、ない
    random_white: bool = False                                           # 白ランオン: 本物の占い師の初日の結果は、人狼でない人への無作為な白(黒は出ない)
    fake_black_first: float = FAKE_BLACK_FIRST                           # 偽の占いが、初手に人狼でない人へ黒を出す重み(白を出す場合を 1)
    dummy: str | None = None                                             # 役欠けあり: 初日犠牲者(最初から死んでいる)。役職は人狼以外のどれかで、占い・霊能・狩人なども欠けうる

    @property
    def dead(self) -> list[str]:
        return [*([self.dummy] if self.dummy else []), *self.executed, *self.bitten, *self.other_dead]

    @property
    def alive(self) -> list[str]:
        gone = set(self.dead)
        return [p for p in self.players if p not in gone]

    def claimants(self, role: str) -> list[str]:
        return [p for p, r in self.claims if r == role]

    def key_players(self) -> list[str]:
        """役職を個別に決める人。ほかの人(灰)は、まとめて数える。"""
        keys = {p for p, _ in self.claims} | set(self.dead) | set(self.wolf_co)
        for r in self.results:
            keys |= {r["player"], r["target"]}
        return [p for p in self.players if p in keys]


@dataclass
class World:
    assign: dict[str, int | str]                         # 主要な人の役職
    left: Counter                                        # 灰に配られる役職(人数)
    count: int                                           # 灰への配り方の数
    tier: int
    reasons: tuple[str, ...] = ()                        # 定番でない理由
    factor: float = 1.0                                  # 結果の出し方の癖(result_factor)

    @property
    def weight(self) -> float:
        return self.count * world_base_weight(self.tier, self.reasons) * self.factor


def setup_roles(setup: str = DEFAULT_SETUP, missing: bool | None = None) -> tuple[dict[str, int], bool]:
    """配役 setup の役職の山と、役欠けありか。役欠けありなら、ダミーの分の村人を1枚足した山(ダミーは、人狼以外の1枚を持つ)。"""
    cfg = SETUPS[setup]
    missing = cfg.missing if missing is None else missing
    roles = dict(cfg.roles)
    if missing:
        roles["村人"] = roles.get("村人", 0) + 1
    return roles, missing


def make_board(setup: str = DEFAULT_SETUP, seers: int = 2, results=(), random_white: bool | None = None, rco: bool = True,
               missing: bool | None = None) -> Board:
    """配役 setup の盤面。参加者は A から順に並べ、占いの名乗りは A から seers 人、霊能の名乗りは最後の1人(12A猫なら K、11A なら J、10A狩なら I)。
    results は、占いの初手の結果(dict の並び。kind・first は補う)。random_white・missing を渡さなければ、配役の約束事のとおり。
    役欠けあり(missing)なら、参加者のあとにダミー(DUMMY)を足す。ダミーは最初から死んでいて、役職は人狼以外のどれか。"""
    cfg = SETUPS[setup]
    roles, missing = setup_roles(setup, missing)
    n = sum(cfg.roles.values())
    players = [chr(ord("A") + i) for i in range(n)]
    if not 0 <= seers <= n - 1:
        raise ValueError("占いの名乗りの人数が多すぎる")
    board = Board(players=players + ([DUMMY] if missing else []), roles=roles, rco=rco, fake_black_first=cfg.fake_black_first,
                  random_white=cfg.random_white if random_white is None else random_white, dummy=DUMMY if missing else None)
    board.claims = [(p, "占い師") for p in players[:seers]] + [(players[-1], "霊能者")]
    board.results = [{"kind": "占い", "first": True, **r} for r in results]
    return board


def domain(board: Board, player: str) -> set[str]:
    """その人がなりうる役職。名乗った人は、その役職か、偽(人狼・狂人)。襲撃で死んだ人は人狼でない。狼COは人狼。"""
    allowed = {r for r, n in board.roles.items() if n > 0}
    for p, role in board.claims:
        if p == player:
            allowed &= {role, "人狼", "狂人"}
    if player in board.bitten or player == board.dummy:
        allowed.discard("人狼")
    if player in board.wolf_co:
        allowed &= {"人狼"}
    return allowed


def truthful(board: Board, assign: dict, result: dict) -> bool:
    """本物の占い師・霊能者の結果は正しい(黒は人狼、白は人狼でない。狂人は白)。本物でなければ、条件なし。"""
    role = ROLE_OF_KIND[result["kind"]]
    p, t = result["player"], result["target"]
    if p not in assign or t not in assign or assign[p] != role:
        return True
    if board.random_white and result["kind"] == "占い" and result.get("first") and result["color"] == "黒":
        return False                                                      # 白ランオン: 本物の初日の結果は、必ず白
    return (assign[t] == "人狼") == (result["color"] == "黒")


REASON_NO_REAL = {"占い師": "占いに本物がいない(潜伏)", "霊能者": "霊に本物がいない(霊の偽)"}
REASON_MISSING = {"占い師": "占いが欠け(初日犠牲者)で、名乗りは全員偽", "霊能者": "霊が欠け(初日犠牲者)で、名乗りは偽"}
REASON_MAD = "狂人が偽に出る"
REASON_NO_MAD = "偽が人狼だけ(狂人が偽に出ない)"
REASON_CUT = "偽の黒が人狼に当たる(切り・偶然)"


def world_judgement(board: Board, assign: dict) -> tuple[int, tuple[str, ...]]:
    """(定番(3)・ありうる(2)・まれ(1), 定番でない理由)。依頼者に聞いた環境を、規則にしたもの。

    - 占い・霊能とも、名乗った人の中に本物がいるのが定番。本物が名乗っていない(潜伏)のは、まれ。
      (占い2・霊能1なら、占いは真と狼、霊は真が定番。霊はたいてい真なので、霊の偽は、名乗りに本物がいないこととして、まれ)
    - 偽が1人なら、人狼が定番。狂人が偽に出るのは、ありうる。
    - 偽が2人以上なら、狂人が1人まじるのが定番(占い3・霊能1なら真狂狼)。人狼だけ(真狼狼)は、ありうる。
      偽が3人以上のときも同じ形と読んだ(推測。依頼者が言ったのは、占い3・霊能1だけ)。
    - 偽の結果が、人狼に黒を当てる(狼が仲間に黒を出す「切り」、狂人の偶然)のは、まれ。
    """
    tier, reasons = 3, []
    for role in CLAIM_ROLES:
        claimants = board.claimants(role)
        if not claimants:
            continue
        if not any(assign[p] == role for p in claimants):
            if board.dummy is not None and assign.get(board.dummy) == role:
                tier = min(tier, 2)                                       # 役欠け: 本物は初日犠牲者。偽の名乗りだけが出ている
                reasons.append(REASON_MISSING[role])
            else:
                tier = min(tier, 1)
                reasons.append(REASON_NO_REAL[role])
        fakes = [p for p in claimants if assign[p] != role]
        mad = any(assign[p] == "狂人" for p in fakes)
        if len(fakes) == 1 and mad:
            tier = min(tier, 2)
            reasons.append(REASON_MAD)
        elif len(fakes) >= 2 and not mad:
            tier = min(tier, 2)
            reasons.append(REASON_NO_MAD)
    for r in board.results:
        p, t = r["player"], r["target"]
        fake = assign[p] in ("人狼", "狂人") and assign[p] != ROLE_OF_KIND[r["kind"]]
        if fake and r["color"] == "黒" and assign[t] == "人狼" and REASON_CUT not in reasons:
            tier = min(tier, 1)
            reasons.append(REASON_CUT)
    return tier, tuple(dict.fromkeys(reasons))


def world_base_weight(tier: int, reasons: tuple[str, ...]) -> float:
    """世界1通りあたりの重み(仮)。段階ごとの数字。ありうるのうち、偽が人狼だけの世界(3-1 の真狼狼)は、別の数字。"""
    if tier == 2 and reasons == (REASON_NO_MAD,):
        return WEIGHT_NO_MAD
    return TIER_WEIGHT[tier]


def world_tier(board: Board, assign: dict) -> int:
    return world_judgement(board, assign)[0]


def result_factor(board: Board, assign: dict, fake_black_first: float | None = None) -> float:
    """結果の出し方の癖(環境の話)。偽の占い(人狼・狂人)が、初手に出した結果にだけかける。
    - 人狼でない人へ黒を出す(人外の凸): fake_black_first。最良手ではないので、白を出す場合より少ない。
    - 白を出す: かけない(1)。偽の対抗白は、本物が出せる相手(狂人)の数え方と同じ重みで数える。
      いちばん有利な真狂狼でも、対抗白を出した側が本物なのは2割(11A のメモ)。
    本物の結果は、真偽の条件(truthful)で決まるので、かけない。人狼への黒(切り・偶然)は、段階(まれ)で扱う。
    二手目以降と、霊能の結果は、癖を聞いていないので、かけない。
    fake_black_first を渡さなければ、盤面(board.fake_black_first)の数字を使う(白ランオンでは、ランオフより小さい)。"""
    if fake_black_first is None:
        fake_black_first = board.fake_black_first
    factor = 1.0
    n, wolves = len(board.players), board.roles.get("人狼", 0)
    for r in board.results:
        if r["kind"] != "占い" or not r.get("first"):
            continue
        if board.random_white and assign[r["player"]] == "占い師" and n - wolves - 1 > 0:
            factor *= (n - 1) / (n - wolves - 1)             # 本物の白は、人狼でない人から無作為(1/(n-人狼-1))で、偽の相手の選び方(1/(n-1))より、その人に当たりやすい
            continue
        if assign[r["player"]] not in ("人狼", "狂人"):
            continue
        if r["color"] == "黒" and assign[r["target"]] != "人狼":
            factor *= fake_black_first
    return factor


def real_claimed(board: Board, assign: dict) -> bool:
    """占い・霊能の本物が、みな名乗った人の中にいる。名乗りが1人もない役職(なのに役職の人数が1以上)は、本物が名乗っていない。
    役欠け: 初日犠牲者が持っている役職は、本物がいない(名乗る人がいなくてよい)。"""
    for role in CLAIM_ROLES:
        n = board.roles.get(role, 0)
        if board.dummy is not None and assign.get(board.dummy) == role:
            n -= 1
        if n > 0 and sum(1 for p in board.claimants(role) if assign[p] == role) != n:
            return False
    return True


def enumerate_worlds(board: Board, fake_black_first: float | None = None) -> list[World]:
    keys = board.key_players()
    free = [p for p in board.players if p not in set(keys)]
    results_by_player: dict[str, list[dict]] = {}
    for r in board.results:
        results_by_player.setdefault(r["player"], []).append(r)
    worlds: list[World] = []
    assign: dict[str, str] = {}
    left = Counter(board.roles)

    def consistent(player: str) -> bool:
        """player を決めたとき、決まっている人どうしの結果の条件を調べる。"""
        for r in board.results:
            if player in (r["player"], r["target"]) and r["player"] in assign and r["target"] in assign:
                if not truthful(board, assign, r):
                    return False
        return True

    def walk(i: int) -> None:
        if i == len(keys):
            if sum(left.values()) != len(free):
                return
            if board.rco and not real_claimed(board, assign):
                return                                                        # 本物は、ロケットCOで名乗っているはず(潜伏はない)
            if board.ongoing:
                alive_wolves = board.roles["人狼"] - sum(1 for p in board.dead if assign[p] == "人狼")
                if alive_wolves <= 0 or alive_wolves >= len(board.alive) - alive_wolves:
                    return                                                # 勝敗が決まっているはずの世界は、合わない
            ways = factorial(len(free))
            for n in left.values():
                ways //= factorial(n)
            tier, reasons = world_judgement(board, assign)
            factor = result_factor(board, assign, fake_black_first)
            if factor > 0:                                                    # 0 は「その出し方はしない」(世界から外す)
                worlds.append(World(dict(assign), +left, ways, tier, reasons, factor))
            return
        player = keys[i]
        for role in sorted(domain(board, player)):
            if left[role] <= 0:
                continue
            assign[player] = role
            left[role] -= 1
            if consistent(player):
                walk(i + 1)
            left[role] += 1
            del assign[player]

    walk(0)
    return worlds


def pattern_label(board: Board, assign: dict) -> str:
    """名乗りの種類の組み合わせ。例: 占い2・霊能1で、占いが本物と人狼、霊能が本物なら「真狼-真」。"""
    parts = []
    for role in CLAIM_ROLES:
        types = []
        for p in board.claimants(role):
            types.append("真" if assign[p] == role else ("狼" if assign[p] == "人狼" else "狂"))
        parts.append("".join(sorted(types, key=TYPE_ORDER.index)) or "なし")
    return "-".join(parts)


def who_is_who(board: Board, assign: dict) -> str:
    """名乗った人ごとの種類。例: 「D=狼 L=真 / J=真」(占い、霊能の順)。"""
    parts = []
    for role in CLAIM_ROLES:
        names = [f"{p}={'真' if assign[p] == role else ('狼' if assign[p] == '人狼' else '狂')}" for p in board.claimants(role)]
        if names:
            parts.append(" ".join(names))
    return " / ".join(parts)


def pattern_table(board: Board, worlds: list[World]) -> list[dict]:
    """(段階, 名乗った人ごとの種類, 理由)ごとの、世界の数と、見込み(重みの割合)。段階の高い順。"""
    rows: dict[tuple, dict] = {}
    for w in worlds:
        key = (w.tier, who_is_who(board, w.assign), w.reasons)
        row = rows.setdefault(key, {"tier": w.tier, "label": pattern_label(board, w.assign), "who": key[1], "reasons": w.reasons, "ways": 0, "weight": 0.0, "worlds": 0})
        row["ways"] += w.count
        row["weight"] += w.weight
        row["worlds"] += 1
    total = sum(r["weight"] for r in rows.values())
    for row in rows.values():
        row["share"] = row["weight"] / total if total else 0.0
    return sorted(rows.values(), key=lambda r: (-r["tier"], -r["share"], -r["ways"], r["who"]))


ROLE_SHORT = {"占い師": "占", "霊能者": "霊"}


def type_shares(board: Board, worlds: list[World], min_tier: int = 1) -> list[tuple[str, str, dict[str, float]]]:
    """名乗った人ごとの、真・狼・狂の見込み(重みの割合)。(役職, 名乗った人, {真, 狼, 狂})の並び。
    重みは仮(TIER_WEIGHT・FAKE_BLACK_FIRST)なので、実戦の比率ではなく、環境の読みを数にした目安。"""
    use = [w for w in worlds if w.tier >= min_tier]
    total = sum(w.weight for w in use)
    out = []
    for role in CLAIM_ROLES:
        for p in board.claimants(role):
            c: Counter = Counter()
            for w in use:
                c["真" if w.assign[p] == role else ("狼" if w.assign[p] == "人狼" else "狂")] += w.weight
            out.append((role, p, {k: (c[k] / total if total else 0.0) for k in TYPE_ORDER}))
    return out


def marginals(board: Board, worlds: list[World], min_tier: int = 1) -> dict[str, dict[str, float]]:
    """人ごとの役職の確率(重みつき)。灰は、みな同じ分布。min_tier 未満の世界は数えない。"""
    use = [w for w in worlds if w.tier >= min_tier]
    total = sum(w.weight for w in use)
    out: dict[str, Counter] = {p: Counter() for p in board.players}
    free = [p for p in board.players if p not in set(board.key_players())]
    for w in use:
        for p, role in w.assign.items():
            out[p][role] += w.weight
        if free:
            m = len(free)
            for role, n in w.left.items():
                for p in free:
                    out[p][role] += w.weight * n / m
    return {p: {r: (v / total if total else 0.0) for r, v in c.items()} for p, c in out.items()}


def confirmed(board: Board, worlds: list[World], min_tier: int) -> dict[str, list[str]]:
    """min_tier 以上の世界のすべてで、人狼(黒)／人狼でない(白)の人。"""
    use = [w for w in worlds if w.tier >= min_tier]
    black, white = [], []
    if use:
        for p in board.key_players():
            if p == board.dummy:
                continue
            if all(w.assign[p] == "人狼" for w in use):
                black.append(p)
            elif all(w.assign[p] != "人狼" for w in use):
                white.append(p)
    return {"黒": black, "白": white}


def wolves_alive(board: Board, world: World) -> int:
    dead_wolves = sum(1 for p in board.dead if world.assign.get(p) == "人狼")
    return board.roles["人狼"] - dead_wolves


def rope_slack(alive: int, wolves: int) -> int:
    """昼の初めの生存者数と人狼の数から、人狼でない人を吊ってしまっても負けない回数(外せる回数)。
    夜は毎回、襲撃で1人減る(狩人の護衛の成功は数えない)。人狼が、残りの人間と同数以上になったら、人狼の勝ち。
    縄数(吊れる回数。最後の1回も外すと負け)は、この数 + 1。"""
    if wolves <= 0:
        return 0
    n, slack = alive, 0
    while n > 0:
        n -= 1                          # 昼: 人狼でない人を吊る
        if wolves >= n - wolves:
            return slack
        n -= 1                          # 夜: 襲撃
        if wolves >= n - wolves:
            return slack
        slack += 1
    return slack


def narrowing_wins(alive: int, wolves: int, known_black: int, greys: int) -> bool:
    """確定した黒を先に吊り、そのあと灰を端から吊っていけば、人狼を吊りきれるか。
    灰の中の人狼が、いちばん最後に固まっている最悪の並びでも、人狼の勝ちにならないなら True(灰詰めで、村の勝ち確)。
    夜は毎回、襲撃で1人減る(護衛の成功は数えない)。"""
    n, w = alive, wolves
    misses = max(0, greys - max(0, w - known_black))            # 灰のうち、人狼でない人の数
    plan = [True] * known_black + [False] * misses + [True] * max(0, w - known_black)
    for hit in plan:
        n -= 1
        if hit:
            w -= 1
        if w <= 0:
            return True
        if w >= n - w:
            return False
        n -= 1
        if w >= n - w:
            return False
    return w <= 0


def next_hang_line(alive: int, wolves: int) -> dict:
    """人狼を1人吊ったあとの盤面: 生存者・人狼・外せる回数(夜の襲撃のあと)。詰み進行の目安。"""
    n, w = alive - 1, wolves - 1        # 昼に人狼を吊る
    if w <= 0:
        return {"alive": n, "wolves": 0, "slack": None, "win": True}
    n -= 1                              # 夜の襲撃
    return {"alive": n, "wolves": w, "slack": rope_slack(n, w), "win": False}


# ---------------------------------------------------------------- 盤面の記録(JSON)


def load_record(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def board_at(record: dict, stage: int) -> Board:
    """記録の events から、段階 stage までに公開された情報の盤面を作る。"""
    key = record.get("setup", DEFAULT_SETUP) if record.get("setup", DEFAULT_SETUP) in SETUPS else DEFAULT_SETUP
    setup = SETUPS[key]
    deck, missing = setup_roles(key, record.get("missing"))
    roles = dict(record.get("roles") or deck)                  # roles を書くときは、役欠けありなら、ダミーの分も入れた山
    board = Board(players=list(record["players"]) + ([DUMMY] if missing else []), roles=roles,
                  ongoing=not record["stages"][stage].get("ended", False), rco=record.get("rco", True),
                  random_white=record.get("random_white", setup.random_white), fake_black_first=record.get("fake_black_first", setup.fake_black_first),
                  dummy=DUMMY if missing else None)
    for e in record["events"]:
        if e["stage"] > stage:
            continue
        kind = e["t"]
        if kind == "co":
            board.claims.append((e["player"], e["role"]))
        elif kind == "result":
            result = {k: e[k] for k in ("kind", "player", "target", "color")}
            # 初手: その人(その役職)の最初の結果。記録に first があれば、それを使う
            result["first"] = e.get("first", not any(r["player"] == e["player"] and r["kind"] == e["kind"] for r in board.results))
            board.results.append(result)
        elif kind == "executed":
            board.executed.append(e["player"])
        elif kind == "bitten":
            board.bitten.append(e["player"])
        elif kind == "dead":
            board.other_dead.append(e["player"])
        elif kind == "wolfco":
            board.wolf_co.append(e["player"])
        else:
            raise ValueError(f"盤面の記録に、知らない種類がある: {kind}")
    return board


def claim_summary(board: Board) -> str:
    parts = []
    for role in CLAIM_ROLES:
        names = []
        for p in board.claimants(role):
            shown = [f"{r['target']}{r['color']}" for r in board.results if r["player"] == p and ROLE_OF_KIND[r["kind"]] == role]
            names.append(p + (f"({'・'.join(shown)})" if shown else ""))
        if names:
            parts.append(f"{role}: {'、'.join(names)}")
    return " / ".join(parts) or "名乗りなし"


def stage_report(record: dict, stage: int) -> str:
    board = board_at(record, stage)
    worlds = enumerate_worlds(board)
    name = record["stages"][stage]["name"]
    lines = [f"== {name}(生存 {len(board.alive)} 人: {' '.join(board.alive)}) =="]
    lines.append(f"名乗り: {claim_summary(board)}")
    if board.executed or board.bitten or board.other_dead or board.wolf_co:
        facts = []
        if board.executed:
            facts.append("処刑 " + "・".join(board.executed))
        if board.bitten:
            facts.append("襲撃で死亡 " + "・".join(board.bitten))
        if board.other_dead:
            facts.append("そのほかの死 " + "・".join(board.other_dead))
        if board.wolf_co:
            facts.append("狼CO " + "・".join(board.wolf_co))
        lines.append("公開された事実: " + "、".join(facts))
    if not worlds:
        lines.append("この情報に合う世界がない(名乗りの前提が成り立たない)。")
        return "\n".join(lines)
    table = pattern_table(board, worlds)
    ways = sum(w.count for w in worlds)
    lines.append(f"合う世界: {ways} 通り(役職の配り方の数。確からしさではない)")
    for row in table:
        if row["tier"] >= 2:
            note = f"  ({'、'.join(row['reasons'])})" if row["reasons"] else ""
            lines.append(f"  [{TIER_NAME[row['tier']]}] {row['label']}: {row['who']}  {row['ways']} 通り・見込み {row['share'] * 100:.0f}%{note}")
    rare = [r for r in table if r["tier"] == 1]
    if rare:
        by_reason: dict[str, int] = {}
        for r in rare:
            for reason in r["reasons"] or ("(理由なし)",):
                by_reason[reason] = by_reason.get(reason, 0) + r["ways"]
        lines.append(f"  [まれ] {len(rare)} 種類 / {sum(r['ways'] for r in rare)} 通り。理由の内訳(重なる): " + "、".join(f"{k} {v}" for k, v in by_reason.items()))
    shares = type_shares(board, worlds)
    if shares and max(x.tier for x in worlds) >= 2:
        parts = [f"{ROLE_SHORT[role]} {p}: " + "・".join(f"{k}{sh[k] * 100:.0f}%" for k in TYPE_ORDER) for role, p, sh in shares]
        lines.append("名乗った人の種類の見込み(仮の環境の重み。目安): " + " / ".join(parts))
    elif shares:
        lines.append("名乗った人の種類の見込み: 定番・ありうるの世界がなく、まれだけなので、出さない")
    for tier in (3, 2, 1):
        c = confirmed(board, worlds, tier)
        if any(w.tier >= tier for w in worlds):
            lines.append(f"{TIER_NAME[tier]}以上の世界のすべてで: 黒 {'・'.join(c['黒']) or 'なし'} / 白 {'・'.join(c['白']) or 'なし'}")
    main = [w for w in worlds if w.tier == max(x.tier for x in worlds)]
    wolves_set = {wolves_alive(board, w) for w in main}
    for w_alive in sorted(wolves_set):
        slack = rope_slack(len(board.alive), w_alive)
        line = next_hang_line(len(board.alive), w_alive)
        tail = "吊れば村の勝ち" if line["win"] else f"人狼を1人吊れば、生存 {line['alive']}・人狼 {line['wolves']}・外せる回数 {line['slack']}"
        lines.append(f"縄({TIER_NAME[max(x.tier for x in worlds)]}の世界): 生存 {len(board.alive)}・人狼 {w_alive} → 外せる回数 {slack}(縄数 {slack + 1})。{tail}")
    top = max(x.tier for x in worlds)
    c_top = confirmed(board, worlds, top)
    black = [p for p in c_top["黒"] if p in board.alive]
    white = [p for p in c_top["白"] if p in board.alive]
    grey = [p for p in board.alive if p not in black and p not in white]
    for w_alive in sorted({wolves_alive(board, w) for w in main}):
        if w_alive <= 0:
            continue
        ok = narrowing_wins(len(board.alive), w_alive, len(black), len(grey))
        verdict = "勝ち確(灰詰めで足りる)" if ok else "足りない(読みが要る)"
        lines.append(
            f"灰詰め({TIER_NAME[top]}の世界。人狼 {w_alive}): 確定黒 {'・'.join(black) or 'なし'}、灰 {len(grey)} 人({'・'.join(grey) or 'なし'})。"
            f"確定黒を先に吊り、灰を端から吊ると、最悪の並びでも → {verdict}"
        )
    truth = record.get("truth")
    if truth:
        t = {p: truth[p] for p in board.key_players()}
        ok = all(t[p] in domain(board, p) for p in t) and all(truthful(board, t, r) for r in board.results)
        tier, reasons = world_judgement(board, t) if ok else (None, ())
        label = pattern_label(board, t) if ok else "(合わない)"
        why = f"({'、'.join(reasons)})" if reasons else ""
        lines.append(f"実際: {label}、{TIER_NAME.get(tier, '—')}{why}" + ("" if ok else " ← 記録か規則が、実際と合っていない"))
    return "\n".join(lines)


def record_report(record: dict) -> str:
    return "\n\n".join(stage_report(record, i) for i in range(len(record["stages"])))


# ---------------------------------------------------------------- 名乗りの組み合わせの一覧


def claim_patterns(seers: int, mediums: int, roles: dict[str, int] | None = None, rco: bool = True, missing: bool = False) -> list[dict]:
    """占い seers 人・霊能 mediums 人が名乗ったときの、名乗りの種類(真・狼・狂)の組み合わせと段階。
    rco(ロケットCO)なら、本物は必ず名乗るので、名乗りが0人の側がある組み合わせは、ない(空のまま)。
    missing(役欠けあり)なら、roles はダミーの分も入れた山で、占い・霊能が欠けた(初日犠牲者が持つ)組み合わせもある。"""
    roles = dict(roles or ROLES_12A_NEKO)
    players = [f"占{i + 1}" for i in range(seers)] + [f"霊{i + 1}" for i in range(mediums)]
    players += [f"灰{i + 1}" for i in range(sum(roles.values()) - len(players) - (1 if missing else 0))]
    if missing:
        players.append(DUMMY)
    board = Board(players=players, roles=roles, rco=rco, dummy=DUMMY if missing else None)
    board.claims = [(f"占{i + 1}", "占い師") for i in range(seers)] + [(f"霊{i + 1}", "霊能者") for i in range(mediums)]
    return pattern_table(board, enumerate_worlds(board))


def patterns_text(rco: bool = True, roles: dict[str, int] | None = None, name: str | None = None, missing: bool = False) -> str:
    """名乗りの数(占い-霊)ごとの、名乗りの種類(真・狼・狂)の組み合わせ。段階ごとにまとめる。
    rco なら、占い・霊能の本物は必ず名乗る(ロケットCO)ので、0 人の側がある組み合わせは、ない(役欠けありなら、欠けたときの 0 人はある)。
    roles を渡すと、その配役の数え方(11A など。役欠けありなら、ダミーの分も入れた山)。"""
    lines = [f"{name + ': ' if name else ''}占い-霊の名乗りの数: 定番 / ありうる / まれ(名乗りの種類の組み合わせ。真=本物、狼=人狼、狂=狂人)"]
    if rco and not missing:
        lines.append("(占い・霊能の本物は、ロケットCO(一発言目の CO)で名乗るので、0-x と x-0 は、ない)")
    elif rco:
        lines.append("(占い・霊能の本物は、ロケットCO(一発言目の CO)で名乗る。ただし、役欠け(初日犠牲者が持つ)で本物がいないことがあるので、0-x と x-0 もある)")
    for s in range(0, 4):
        for m in range(0, 3):
            if s == 0 and m == 0:
                continue
            if rco and not missing and (s == 0 or m == 0):
                continue
            by_tier: dict[int, list[str]] = {3: [], 2: [], 1: []}
            for r in claim_patterns(s, m, roles=roles, rco=rco, missing=missing):
                if r["label"] not in by_tier[r["tier"]]:
                    by_tier[r["tier"]].append(r["label"])
            lines.append(f"{s}-{m}: " + " | ".join(f"{TIER_NAME[t]}: {'、'.join(by_tier[t]) or 'なし'}" for t in (3, 2, 1)))
    return "\n".join(lines)
