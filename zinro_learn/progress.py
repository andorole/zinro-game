"""進行の比較: 占いロラ・グレランなどの進行ごとに、村の勝率を見積もる(試算)。

盤面(board.py)の世界の重みから、役職の割り当てを無作為に引く。そのうえで、村の進行(吊り方)と、狼の噛み方を決めて、
勝敗が付くまで日と夜を動かし、村が勝つ割合を数える。11A のメモ(`knowledge/prob_11a.md` の 2-3)と同じ型の、読みゼロの進行を比べる。

村の進行(毎日1人を吊る。霊能の結果は、翌朝に霊能が生きていれば出る):
- グレー: 毎日、名乗っていない人(灰)から無作為に吊る。灰がいなければ、占いの名乗りを吊る。
- 占いロラ: 占いの名乗りを、狼の見込みが高い順に吊る。ただし、いちばん狼の見込みが低い人(本物と見る人)は残す。そのあと灰。
- 黒スト: 占いの名乗りを同じ順に吊り、霊能の結果が黒(人狼)になったら、灰に切り替える。白が続くうちは、占いを吊る。
  最後の1人は、ほかの名乗りの全員が白と分かった(その人は人狼と決まる)ときだけ吊る。霊能の結果が出ないときは、最後の1人を残す。
- ロラ完遂: 占いの名乗りを、本物と見る人も含めて、すべて吊る。そのあと灰。
どの進行も、結果で黒を出された人(黒先)を、いちばん先に吊る(先黒吊り。標準)。black_first が偽なら、占い吊り優先: 占いを吊る進行は、
占いの名乗りを先に吊り、黒先は占いを吊り終えてから吊る(依頼者の言う「進行提示」の、黒吊りと占いロラの違い)。

狼の噛み方(毎晩1人):
- 灰: 灰(名乗っていない人)から無作為に噛む。11A のメモの基本の前提。
- 名乗り: 狼でない占い・霊能の名乗りを先に噛む(狼は、本物と狂人を見分けられないので、区別しない)。いなければ灰。

狩人の護衛(毎晩1人。狼がその人を噛もうとしたら、噛みは失敗する。狩人が生きているあいだだけ):
- なし: 護衛を入れない。
- 霊能: 霊能を護衛しつづける(霊護衛固定)。
- 黒出し: 結果で黒を出した占いの名乗りを護衛しつづける(黒出し占い護衛固定)。
- 環境: 初手で黒が出ていれば、黒を出した占いを護衛する。なければ、真目の占いか霊能(依頼者。霊能を先にする。真目の占いは、狼の見込みが
  いちばん低い名乗り)。守る相手が死んでいたら、次の候補を守る。

占いの夜の結果(2日目以降。seer_results が真のとき):
- 占いの名乗りで生きている人は、毎晩1人を占い、翌朝、生きていれば結果を出す(夜に噛まれた占いは、結果を出せない)。相手は、灰から無作為。
- 本物は正しい色を出す。偽の人狼は、仲間に白を出し(身内切りは、戦術として強くないので、しない)、人狼でない人には、黒を出す
  重み FAKE_BLACK_LATER(白を出す場合を 1)で出す。偽の狂人は、相手が何であっても、同じ重みで黒を出す。
  依頼者の話「偽の二手目は、だいたい白」に合わせて、FAKE_BLACK_LATER は、初手の FAKE_BLACK_FIRST より小さい(仮)。
- 偽の人狼は、初手や次手で、仲間を囲う(仲間に白を出す)のが基本(依頼者の話)。次手(夜1の結果)では、灰の仲間の人狼がいれば、
  ENCLOSE_NEXT の割合で、その仲間に白を出す(仮)。初手の囲いは、盤面の重みには入れていない。
- 村は、「本物と見る占い」(狼の見込みがいちばん低い名乗り)の結果だけを信じる。黒は黒先として吊り、白を貰った人は、灰の無作為の吊りから外す。
  ほかの占いの結果は使わない。本物と見る占いが、実は偽なら、村はその嘘の結果に従う。

猫又(cat。依頼者の説明):
- 吊られたら、生存者(自分以外)からランダムに1人を道連れにする。人狼を連れていく(人狼道連れ)こともあれば、村を連れていく(村道連れ)こともある。
  だから村は、本物の猫又を吊りたくない。
- 噛まれたら、人狼のうちランダムに1人を道連れにする(人狼online仕様)。よみ鯖仕様は「噛んだ人狼」。噛む人が毎晩ランダムなら、同じ。
- off: 猫又の力を数えない(最初の試算)。hidden: 猫又は名乗らず、灰にいる(吊りと噛みの道連れが起きる)。
  open: 猫又が名乗って、村は吊らず、狼は噛まない(ほかに候補があるあいだ)。ただし、人狼2人で夜に6人のときは、
  OPEN_CAT_BITE の割合で、猫又を噛む(噛めば一気に最終日に行ける。依頼者の話。人狼が1人(LW)のときは、絶対に噛めない)。
  ランダムな道連れと、猫の対抗(人狼や狂人の偽の猫)が出ることがあるので、最近はあまり噛まない、とのこと(仮に 2割)。
  counter: 猫又が名乗り、COUNTER_CAT の割合で、対抗の猫(偽の猫)が出る。対抗は、名乗っていない人狼(COUNTER_CAT_WOLF の割合)か狂人。
  いまの環境では、猫COに対抗猫が出たら猫吊りが基本(依頼者。占いへの対抗黒と同じ型で、環境上確率が高い盤面を想定した吊り)。
  猫が2人名乗っていると、村は猫を吊る: 黒を出された方(黒先)。なければ、先に出た方(FAKE_CAT_FIRST の割合で、先に出たのが偽)。
  吊った猫が本物なら、道連れが起きる(依頼者: 道連れが起きたらほぼ負け)。道連れが起きなければ、偽を吊れたと分かるので、
  残る猫は本物として吊らない(放置)。本物が先に死んで偽が残ったら、その偽を、黒先のあとに吊る。
  gidra: 猫又は隠れていて、昼1に出るのは、黒を刺されたとき(必ず出る)と、吊りを指定されたとき(単体で名乗る=ギドラ。狩人は出ない)だけ
  (依頼者)。黒を刺された猫は、進行が先黒吊りなら必ず出る(伏せたまま吊られることはない)。名乗っても、黒先として吊られる(貫通される)。人狼側は猫を
  確定させたくないので、対抗猫がほぼ出る(COUNTER_CAT_BLACK)。占いロラ進行になったときは、猫が伏せることがあると聞いたが、まだ入れていない
  (いまの環境では、先黒吊りになる可能性が高い)。black_first が偽(占い吊り優先)のときは、黒を刺された猫が CAT_HIDE_SEERS_FIRST の割合で伏せる(仮)。
  伏せた猫は、黒先として吊られる番になったら、そこで名乗る。指定されて出た猫の対抗猫は、COUNTER_CAT で、あとから出る。
  指定されて出た猫に対抗猫が出なければ、村は吊り先を選び直す(猫は確定して放置)。出れば猫吊りで、先に出た本物を吊る形になる。
  偽の猫が、真猫より先に自分から出ることもある(FAKE_CAT_PROACTIVE の割合で、試合の初めから出ている)。そのときは、真猫が対抗として露出し、
  先に出た偽の猫を吊る形になる。先に出たのが偽の割合は、この2つの流れの比で決まる(依頼者の「6割くらい」に近づくように置いた)。
  この動きは、依頼者の言う炙り(偽の猫として扱われると分かっていながら猫COをして、対抗を出す。指定されたときなどの足掻き)に近いが、
  指定された人外が出る、という結びつきは入れていない。対抗伏せ貫通(猫COを偽と割り切って、対抗を出さずに吊る)は、いまはやっていないので、
  対抗が出ない猫は吊らない(依頼者)。

狩人のギドラ(hunter。依頼者の説明):
- off: 狩人は名乗らない(指定されたら、そのまま吊られる)。
- gidra: 吊りを指定された本物の狩人は、ギドラCOをして吊りを避ける(GIDRA_HUNTER。依頼者: 本指定のタイミングで、狩もギドラCOをする)。
  村は、名乗った人を除いて、吊り先を選び直す。名乗った狩人は、ほかに候補があるあいだ吊られない(狩COを偽と割り切って吊る「狩貫通」は、
  初手にはしない、と聞いた。後の日の狩貫通は、いまは入れていない)。名乗っている狩人(人狼でない)は、狼が HUNTER_BITE の割合で噛みに来る(仮)。
  2人の狩人が名乗ったら、先に出た方を吊る(猫吊りと同じ置き方)。
- fake: gidra に加えて、黒なしで昼1に指定された人狼・狂人が、FAKE_HUNTER_FIRST の割合で、偽の狩人COで吊りを避ける(依頼者: 初手の回避は
  狩が良いことがある。狩貫通は初手にはしない)。本物の狩人は、HUNTER_COUNTER の割合で、対抗として出る。対抗が出れば、指定された(先に出た)
  偽を吊る。出なければ、偽の狩人は吊られずに残り、村は吊り先を選び直す。人外が偽の狩人を名乗るのは、昼1の最初の指定だけ(後の日は入れていない)。

同数のときの票(PP・RPP。依頼者の説明。rpp が真のとき):
- 人外側(人狼と狂人)の人数が、村(人外側でない人)の人数以上になると、人外側が同じ村人1人に票を入れる。人数が上回れば、必ず通る(PP)。
  同数なら、村が人外側の1人にまとまっても同数で、抽選になる(RPP。「同数なら抽選」の部屋の決まり)。村は、人外側の1人(だれが狂人かは
  分からないので、無作為。村が黒と信じている人が人外側にいれば、その人)にまとまる、と置く。半々で、人外側が選んだ村人が吊られるか、
  村が選んだ人外側の1人が吊られる。
  人狼3・狂人1・村4(昼2。真猫を吊って道連れが村に当たった形)では、村の勝ちは 1/32(約 3%)になる(依頼者: ほぼ負け)。
- 人外側に狂人がいないと、人数が同数以上の時点で人狼の勝ちなので、この操作は起きない。

標準(`python -m zinro_learn progress` と、知識メモの表): 護衛 env、猫又 gidra、同数の票あり。関数の既定は、護衛なし・猫又 hidden・同数の票あり
(試験と、11A のメモとの比較のため。呼ぶ側が選ぶ)。

入れていないもの(大きなもの): 2-2 での猫の出方(霊能2人の盤面が未対応)、狩人のギドラCO、黒なしで指定された人外の偽の狩人COと炙り
(依頼者: 狩貫通は初手にはしないので、偽の狩人COは初手の回避に通りやすい)、3日目の猫CO、票が割れること、発言からの村の読み
(霊能の報告からの読みは reads で入れた)。
狂人は、人間として数える。人狼が人間と同数以上になれば、人狼の勝ち。人狼が全滅すれば、村の勝ち。
"""
from __future__ import annotations

import random
from bisect import bisect
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from itertools import accumulate

from .board import Board, World, enumerate_worlds, marginals, pattern_label

FAKE_BLACK_LATER = 0.05          # 仮。偽の占いが、2日目以降の夜に、人狼でない人へ黒を出す重み(白を出す場合を 1)。初手(0.15)より小さい
ENCLOSE_NEXT = 0.5               # 仮。偽の人狼が、次手(夜1の結果)で、灰の仲間に白を出す(囲う)割合
OPEN_CAT_BITE = 0.2              # 仮。名乗っている猫又を、人狼2人・夜に6人のときに、狼が噛む割合(依頼者: たまに噛む。最近はあまり噛まない)
COUNTER_CAT = 0.7                # 依頼者の話(その割合でよい。対抗猫はまあまあ出る)。猫又が名乗ったあと、対抗の猫(偽の猫)が出る割合
COUNTER_CAT_WOLF = 0.7           # 依頼者の話(その割合でよい)。対抗の猫が人狼の割合(残りは狂人。人狼 : 狂人 = 7 : 3)
FAKE_CAT_FIRST = 0.6             # 仮。counter で、猫が2人名乗ったとき、先に出た方が偽の割合。依頼者: 黒がなければ、どちらかといえば先に出た方を吊る
FAKE_CAT_PROACTIVE = 0.15        # 仮。gidra で、偽の猫が、真猫より先に自分から出ている割合(依頼者の「先に出たのが偽は6割くらい」に近づくように置いた。占いロラで 0.66。炙りに近い動きだが、指定との結びつきは入れていない)
COUNTER_CAT_BLACK = 0.9           # 仮。黒を刺された猫が名乗ると、人狼側は猫を確定させたくないので、対抗猫がほぼ出る(依頼者: 対抗が出て、真猫が貫通されるのが基本)
CAT_HIDE_SEERS_FIRST = 0.5        # 仮。占い吊り優先の進行(黒先を吊らない)のとき、黒を刺された猫が伏せる割合(依頼者: 伏せる可能性がある。噛まれないので、出てもよいとも思う)
GIDRA_CAT = 1.0                  # 依頼者の話(指定されてのギドラは推奨。指示役が単体で出してほしいと言えば、単体で出る)。指定された猫が名乗る割合
GIDRA_HUNTER = 1.0               # 依頼者の話(本指定のタイミングで、指定された狩人もギドラCOをする)。指定された狩人が名乗る割合
FAKE_HUNTER_FIRST = 0.5          # 仮。fake で、黒なしで昼1に指定された人狼・狂人が、偽の狩人COで吊りを避ける割合(依頼者: 初手の回避は狩が良いことがある。狩貫通は初手にはしない。かなり悩ましい)
HUNTER_COUNTER = 0.5             # 仮。偽の狩人が出たとき、本物の狩人が対抗として出る割合(まだ聞いていない)
HUNTER_BITE = 0.7                # 仮。名乗っている狩人(人狼でない)を、狼が噛みに来る割合(まだ聞いていない)
HUNTERS = ("off", "gidra", "fake")
HUNTER_NAME = {"off": "狩人は名乗らない", "gidra": "狩人は指定されたら名乗る", "fake": "狩人は指定されたら名乗り、人外も昼1の指定で偽の狩人を名乗る"}
CATS = ("off", "hidden", "open", "counter", "gidra")
CAT_NAME = {"off": "猫又の力なし", "hidden": "猫又は隠れている", "open": "猫又は名乗っている", "counter": "猫又は名乗り、対抗猫が出る",
            "gidra": "猫又は隠れていて、黒を刺されたら・指定されたら名乗る"}
POLICIES = ("grey", "roll_keep", "roll_stop", "roll")
POLICY_NAME = {"grey": "グレー", "roll_keep": "占いロラ", "roll_stop": "黒スト", "roll": "ロラ完遂"}
BITES = ("grey", "claim")
BITE_NAME = {"grey": "灰を噛む", "claim": "名乗りを噛む"}
GUARDS = (None, "medium", "blacksayer", "env")
GUARD_NAME = {None: "護衛なし", "medium": "霊護衛固定", "blacksayer": "黒出し占い護衛固定", "env": "環境の護衛"}


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


def pick_fake_cat(roles: dict[str, str], alive: set[str], claimants: set[str], rng: random.Random) -> str | None:
    """偽の猫になる人: 占いを名乗っていない人狼(COUNTER_CAT_WOLF の割合)か狂人。いなければ None。"""
    free = [p for p in sorted(alive) if p not in claimants]
    wolves = [p for p in free if roles[p] == "人狼"]
    mads = [p for p in free if roles[p] == "狂人"]
    pool = (wolves if rng.random() < COUNTER_CAT_WOLF else mads) or wolves or mads
    return rng.choice(pool) if pool else None


def counter_cat(roles: dict[str, str], alive: set[str], claimants: set[str], rng: random.Random) -> tuple[str | None, bool]:
    """名乗った猫又に対抗して出る偽の猫と、その人が先に出たか。(名乗りでない人狼か狂人から。出ないときは (None, False))"""
    if rng.random() >= COUNTER_CAT:
        return None, False
    fake = pick_fake_cat(roles, alive, claimants, rng)
    if fake is None:
        return None, False
    return fake, rng.random() < FAKE_CAT_FIRST


def play(prep: Prepared, roles: dict[str, str], policy: str, bite: str, rng: random.Random, trace: list | None = None,
         guard: str | None = None, seer_results: bool = True, cat: str = "hidden", rpp: bool = True, black_first: bool = True,
         reads: bool = True, hunter: str = "off") -> bool:
    """1回の試合を動かす。村が勝てば True。trace があれば、(種類, 人, 色) の出来事を足す。
    black_first が偽なら、占い吊り優先: 占いを吊る進行は、黒を出された人(黒先)より、占いの名乗りを先に吊る(黒先は、占いを吊り終えてから)。
    reads が真なら、村は霊能の報告で占いを読む(偽と分かった占いを先に吊る。結果は信じない。黒を当てた占いを、本物と見る)。
    hunter は、狩人のギドラ(off=名乗らない、gidra=指定された本物の狩人が名乗る、fake=人外も昼1の指定で偽の狩人を名乗る)。"""
    if cat not in CATS:
        raise ValueError(f"知らない猫又の扱い: {cat}")
    if hunter not in HUNTERS:
        raise ValueError(f"知らない狩人の扱い: {hunter}")
    board = prep.board
    black_sayer = next((r["player"] for r in board.results if r["kind"] == "占い" and r["color"] == "黒"), None)
    if guard not in GUARDS:
        raise ValueError(f"知らない護衛: {guard}")
    guarded = {None: None, "medium": prep.medium, "blacksayer": black_sayer, "env": None}[guard]
    claimants = set(prep.seers) | ({prep.medium} if prep.medium else set())
    alive = set(board.players)
    for p in board.dead:                                  # 盤面にすでにある死者
        alive.discard(p)
    real_cat = next((p for p in sorted(alive) if roles[p] == "猫又"), None)
    revealed = cat in ("open", "counter") and real_cat is not None        # 真猫が名乗っているか(gidra は、出る条件を満たすまで隠れている)
    fake_cat, fake_first, fake_out = None, False, False   # 偽の猫、先に出たのが偽か、偽の猫が名乗っているか
    if cat == "counter" and real_cat is not None:
        fake_cat, fake_first = counter_cat(roles, alive, claimants, rng)
        fake_out = fake_cat is not None
    elif cat == "gidra" and real_cat is not None and rng.random() < FAKE_CAT_PROACTIVE:
        fake_cat = pick_fake_cat(roles, alive, claimants, rng)             # 偽の猫が、真猫より先に自分から出ている
        fake_first = fake_out = fake_cat is not None
        if fake_out and trace is not None:
            trace.append(("fakecat", fake_cat, "先に出る"))
    cat_hides = cat == "gidra" and not black_first and real_cat is not None and rng.random() < CAT_HIDE_SEERS_FIRST       # 占い吊り優先のとき、黒を刺された猫が伏せるか
    real_hunter = next((p for p in sorted(alive) if roles[p] == "狩人"), None)
    hunter_out: list[str] = []                            # 狩人を名乗っている人(名乗った順。本物と、人外の偽)
    blacks = sorted({r["target"] for r in board.results if r["color"] == "黒" and r["target"] in alive}, key=lambda p: -prep.wolf_prob[p])
    public = [(r["player"], r["target"], r["color"]) for r in board.results if r["kind"] == "占い" and r["player"] in prep.seers]   # 公開された占いの結果
    black_src: dict[str, str] = {}                        # 黒を出された人 → 黒を出した占い(偽と分かったら、その黒は信じない)
    for sr, t, c in public:
        if c == "黒":
            black_src.setdefault(t, sr)
    safe_src: dict[str, str] = {}
    refuted: set[str] = set()                             # 霊能の報告と食い違う結果を出して、偽と分かった占い
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

    def cats() -> tuple[bool, str | None, set[str]]:
        """(猫が2人名乗っていて決着前か, 偽と分かった猫, 名乗っている猫)。猫又の道連れが起きれば、どちらが本物か分かる。"""
        if cat == "off" or cat == "hidden" or real_cat is None:
            return False, None, set()
        real_out = revealed and real_cat in alive
        fake_alive = fake_out and fake_cat is not None and fake_cat in alive
        exposed = ({real_cat} if real_out else set()) | ({fake_cat} if fake_alive and real_out else set())
        return real_out and fake_alive, (fake_cat if fake_alive and real_cat not in alive else None), exposed

    def reveal(reason: str) -> None:
        """真猫が名乗る。偽の猫がまだ出ていなければ、COUNTER_CAT の割合で、あとから対抗の猫が出る。"""
        nonlocal revealed, fake_cat, fake_first, fake_out
        revealed = True
        if trace is not None:
            trace.append(("cat", real_cat, reason))
        if not fake_out and rng.random() < (COUNTER_CAT_BLACK if reason == "黒" else COUNTER_CAT):
            fake = pick_fake_cat(roles, alive, claimants, rng)
            if fake is not None:
                fake_cat, fake_first, fake_out = fake, False, True
                if trace is not None:
                    trace.append(("fakecat", fake, "あとから出る"))

    def hang(target: str) -> None:
        alive.discard(target)
        unreported.append(target)
        if trace is not None:
            trace.append(("hang", target, "人狼" if roles[target] == "人狼" else "人間"))
        if cat != "off" and roles[target] == "猫又" and alive:
            taken = rng.choice(sorted(alive))                             # 吊られた猫又は、生存者からランダムに1人を道連れにする
            alive.discard(taken)
            if trace is not None:
                trace.append(("takealong", taken, "人狼" if roles[taken] == "人狼" else "人間"))

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
        unreported.clear()
        for seer, t, c in reports:                        # 朝: 夜に出た占いの結果。噛まれた占いは出せない
            if seer not in alive:
                continue
            if trace is not None:
                trace.append(("result", seer, t + c))
            public.append((seer, t, c))
            if seer == kept:                              # 村は、本物と見る占いの結果だけを信じる
                if c == "黒" and t in alive and t not in blacks:
                    blacks.append(t)
                    black_src[t] = seer
                elif c == "白":
                    safe.add(t)
                    safe_src[t] = seer
        reports = []
        if reads:
            for sr, t, c in public:
                if sr not in refuted and colors.get(t, c) != c:
                    refuted.add(sr)                       # 霊能の報告と食い違う結果を出した占いは、偽と分かる
                    if trace is not None:
                        trace.append(("refuted", sr, t + c))
            if refuted:
                blacks = [b for b in blacks if black_src.get(b) not in refuted]       # 偽と分かった占いの黒・白は、信じない
                safe = {q for q in safe if safe_src.get(q) not in refuted}
            confirmed = [sr for sr, t, c in public if c == "黒" and colors.get(t) == "黒" and sr not in refuted and sr in alive]
            if kept in refuted or (confirmed and kept not in confirmed):
                choices = confirmed or [q for q in reversed(order) if q in alive and q not in refuted]    # 黒を当てた占いを、本物と見る
                kept = choices[0] if choices else None
        alive_blacks = [p for p in blacks if p in alive]
        if cat == "gidra" and real_cat in alive and not revealed:
            if fake_out and fake_cat in alive:
                reveal("対抗")                            # 偽の猫が出ているので、真猫は対抗として露出する(依頼者: 対抗が居たら基本的に露出)
            elif real_cat in alive_blacks and not cat_hides:
                reveal("黒")                              # 黒を刺された猫は、先黒吊りなら必ず出る(依頼者)。占い吊り優先のときは、伏せることがある
        pending, known_fake, exposed = cats()

        def grey_pool() -> list[str]:
            held = exposed | set(hunter_out)                               # 名乗っている猫又・狩人は、ほかに候補があるあいだ吊らない
            everyone = [p for p in alive if p not in claimants and p not in held] or [p for p in alive if p not in claimants]
            return [p for p in everyone if p not in safe] or everyone      # 白を貰った灰は、無作為の吊りから外す

        alive_seers = [p for p in order if p in alive]
        hanged_seer_colors = [colors.get(p) for p in order if p not in alive]

        def by_policy(greys: list[str]) -> tuple[str | None, bool]:
            """(吊り先, 占いの名乗りを吊るか)。"""
            if policy == "grey":
                return (rng.choice(sorted(greys)) if greys else None), False
            if policy == "roll":
                if alive_seers:
                    return alive_seers[0], True
                return (rng.choice(sorted(greys)) if greys else None), False
            if policy == "roll_keep":
                rolling = [p for p in alive_seers if p != kept]                 # 本物と見る人は残す
                if rolling:
                    return rolling[0], True
                return (rng.choice(sorted(greys)) if greys else None), False
            if policy == "roll_stop":
                others = [p for p in alive_seers if p != kept]
                last_is_wolf = sum(1 for c in hanged_seer_colors if c == "白") == len(order) - 1 and kept in alive_seers
                if "黒" in hanged_seer_colors or not (others or last_is_wolf):
                    if greys:
                        return rng.choice(sorted(greys)), False
                    return (alive_seers[0], True) if alive_seers else (None, False)
                if others:
                    return others[0], True
                return kept, True                                               # ほかの名乗りが全員白なら、最後の1人は人狼と決まる
            raise ValueError(f"知らない進行: {policy}")

        def fallback() -> str:
            rest = sorted(alive_seers) or sorted(alive)                         # 候補が尽きたとき: 占い、霊能、残る誰か
            return rng.choice(rest)

        target = None
        from_policy = False
        fakes_alive = [p for p in order if p in refuted and p in alive]
        side = sorted(p for p in alive if roles[p] in ("人狼", "狂人"))                 # 人外側(人狼と狂人)
        villagers = sorted(p for p in alive if roles[p] not in ("人狼", "狂人"))
        if rpp and villagers and any(roles[p] == "狂人" for p in side) and len(side) >= len(villagers):
            # PP・RPP: 人外側が同じ村人に票を入れる。上回れば通る。同数なら、村が人外側の1人にまとまっても同数で、抽選
            pick = rng.choice(villagers)
            if len(side) > len(villagers):
                target = pick
                if trace is not None:
                    trace.append(("pp", pick, ""))
            else:
                against = next((p for p in alive_blacks if p in side), None) or rng.choice(side)     # 村は、黒と信じる人が人外側にいればその人
                target = pick if rng.random() < 0.5 else against
                if trace is not None:
                    trace.append(("rpp", pick, against))
        elif fakes_alive:
            target = fakes_alive[0]                       # 偽と分かった占い
        elif alive_blacks and black_first:
            target = alive_blacks[0]                      # 黒先
        elif known_fake is not None:
            target = known_fake                           # 本物の猫が先に死んで、偽と分かった猫
        elif pending:
            target = fake_cat if fake_first else real_cat # 猫が2人名乗っている: 黒がなければ、先に出た方を吊る(吊った猫の道連れで、本物か分かる)
        else:
            target, from_seer = by_policy(grey_pool())
            if alive_blacks and not black_first and not from_seer:
                target = alive_blacks[0]                  # 占い吊り優先: 占いを吊り終えたら、黒先
            else:
                if target is None:
                    target = fallback()
                from_policy = True
        if cat == "gidra" and not from_policy and target == real_cat and not revealed and target in alive_blacks:
            reveal("黒")                                  # 黒先として吊られる猫は、名乗る(必ず出る)。伏せていても、ここで出る
        for _attempt in range(4 if hunter != "off" else 1):       # 名乗って避けた人がいれば、村は吊り先を選び直す(選び直した先も指定なので、また名乗ることがある)
            if not from_policy:
                break
            spared = False
            if cat == "gidra" and target == real_cat and not revealed and rng.random() < GIDRA_CAT:
                # 吊りを指定された猫は、単体で名乗って(ギドラ)、吊りを避ける。対抗猫が出れば猫吊り、出なければ吊り先を選び直す
                reveal("指定")
                pending, known_fake, exposed = cats()
                if pending:
                    target = fake_cat if fake_first else real_cat
                    break
                spared = True
            elif hunter != "off" and target == real_hunter and target not in hunter_out and rng.random() < GIDRA_HUNTER:
                # 吊りを指定された狩人は、ギドラCOをして吊りを避ける(本指定のタイミングで、狩もギドラCOをする)
                earlier = [p for p in hunter_out if p in alive]
                hunter_out.append(target)
                if trace is not None:
                    trace.append(("hunter", target, "指定"))
                if earlier:
                    target = earlier[0]                               # 狩人が2人名乗った(偽が先に出ていた): 先に出た方を吊る
                    break
                spared = True
            elif (hunter == "fake" and night == 0 and roles[target] in ("人狼", "狂人") and target not in claimants
                  and real_hunter not in hunter_out and rng.random() < FAKE_HUNTER_FIRST):
                # 黒なしで昼1に指定された人狼・狂人は、偽の狩人COで吊りを避ける(狩貫通は初手にはしない)
                hunter_out.append(target)
                if trace is not None:
                    trace.append(("fakehunter", target, "指定"))
                if real_hunter in alive and rng.random() < HUNTER_COUNTER:
                    hunter_out.append(real_hunter)                    # 本物の狩人が対抗として出る: 指定された(先に出た)偽を吊る
                    if trace is not None:
                        trace.append(("hunter", real_hunter, "対抗"))
                    break
                spared = True
            if not spared:
                break
            target, _ = by_policy(grey_pool())
            if target is None:
                target = fallback()
        hang(target)
        wolves, humans = counts()
        if wolves == 0:
            return True
        if wolves >= humans:
            return False
        # 夜: 狼が1人噛む
        _, _, exposed = cats()                            # 名乗っている猫又は、ほかに候補があるあいだ噛まない
        nonwolf = sorted(p for p in alive if roles[p] != "人狼")
        open_nonwolf = [p for p in nonwolf if p not in exposed] or nonwolf
        if bite == "claim":
            pool = [p for p in open_nonwolf if p in claimants] or [p for p in open_nonwolf if p not in claimants] or open_nonwolf
        elif bite == "grey":
            pool = [p for p in open_nonwolf if p not in claimants] or open_nonwolf
        else:
            raise ValueError(f"知らない噛み方: {bite}")
        wolves_now = sum(1 for p in alive if roles[p] == "人狼")
        if exposed & set(nonwolf) and wolves_now == 2 and len(alive) == 6 and rng.random() < OPEN_CAT_BITE:
            pool = sorted(exposed & set(nonwolf))                          # 人狼2人・夜に6人: 猫又を噛めば、一気に最終日に行ける
        if hunter != "off":
            out_nonwolf = sorted(p for p in hunter_out if p in alive and roles[p] != "人狼")      # 狼は、本物の狩人と狂人の偽を見分けられない
            if out_nonwolf and rng.random() < HUNTER_BITE:
                pool = out_nonwolf                                         # 名乗っている狩人を、護衛の前に噛みに来る
        victim = rng.choice(pool)
        if guard == "env":                                # 環境の護衛: 黒を出した占い、なければ霊能、なければ真目の占い(生きている人)
            guarded = next((p for p in (black_sayer, prep.medium, kept) if p is not None and p in alive), None)
        if guarded is not None and victim == guarded and any(roles[p] == "狩人" for p in alive):
            if trace is not None:
                trace.append(("guard", victim, ""))               # 護衛が成功して、だれも死なない
        else:
            alive.discard(victim)
            if trace is not None:
                trace.append(("bite", victim, ""))
            if cat != "off" and roles[victim] == "猫又":
                mates = sorted(p for p in alive if roles[p] == "人狼")
                if mates:
                    taken = rng.choice(mates)                             # 噛まれた猫又は、人狼のうちランダムに1人を道連れにする
                    alive.discard(taken)
                    if trace is not None:
                        trace.append(("takealong", taken, "人狼"))
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
             guard: str | None = None, seer_results: bool = True, cat: str = "hidden", rpp: bool = True,
             where: Callable[[dict[str, str]], bool] | None = None, black_first: bool = True, reads: bool = True,
             hunter: str = "off") -> dict:
    """進行 policy・噛み方 bite で n 回動かした、村の勝率。構成(占いの名乗りの種類の組み合わせ)別の割合も返す。
    where があれば、役職の割り当てがその条件を満たす世界だけを数える(例: 黒を出された人が猫又の世界)。"""
    prep = prep or prepare(board)
    world_rng, play_rng = random.Random(seed), random.Random(seed + 1)   # 世界の引きは、進行によらず同じ列にする(比べやすい)
    wins, total = 0, defaultdict(int)
    by_win: dict[str, int] = defaultdict(int)
    done = 0
    for _ in range(n * (200 if where else 1)):
        roles, label = sample_world(prep, world_rng)
        if where is not None and not where(roles):
            continue
        total[label] += 1
        if play(prep, roles, policy, bite, play_rng, guard=guard, seer_results=seer_results, cat=cat, rpp=rpp, black_first=black_first, reads=reads,
                hunter=hunter):
            wins += 1
            by_win[label] += 1
        done += 1
        if done == n:
            break
    if done == 0:
        raise ValueError("条件に合う世界が引けなかった")
    rate = wins / done
    return {
        "rate": rate,
        "stderr": (rate * (1 - rate) / done) ** 0.5,
        "n": done,
        "by_label": {k: {"share": total[k] / done, "rate": by_win[k] / total[k]} for k in sorted(total, key=lambda k: -total[k])},
    }


def compare(board: Board, n: int = 20000, seed: int = 1, policies=POLICIES, bites=BITES, guard: str | None = None,
            seer_results: bool = True, cat: str = "hidden", rpp: bool = True, black_first: bool = True, reads: bool = True,
            hunter: str = "off") -> dict:
    """進行 × 噛み方の、村の勝率の表。{(bite, policy): win_rate の結果}。同じ世界の引きで比べる(seed を共通にする)。"""
    prep = prepare(board)
    return {(b, p): win_rate(board, p, b, n, seed, prep, guard, seer_results, cat, rpp, black_first=black_first, reads=reads, hunter=hunter)
            for b in bites for p in policies}


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


def compare_text(board: Board, title: str, n: int = 20000, seed: int = 1, guard: str | None = None, seer_results: bool = True,
                 cat: str = "hidden", rpp: bool = True, black_first: bool = True, reads: bool = True, hunter: str = "off") -> str:
    table = compare(board, n, seed, guard=guard, seer_results=seer_results, cat=cat, rpp=rpp, black_first=black_first, reads=reads, hunter=hunter)
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
