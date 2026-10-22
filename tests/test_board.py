import json
import unittest
from collections import Counter
from itertools import permutations
from pathlib import Path

from zinro_learn.board import (
    DUMMY, FAKE_BLACK_FIRST, FAKE_BLACK_FIRST_RANDOM_WHITE, REASON_MISSING, ROLES_10A_KARI, ROLES_12A_NEKO, SETUPS, Board, board_at, claim_patterns, confirmed,
    enumerate_worlds, load_record, make_board, narrowing_wins, next_hang_line, marginals, pattern_label, patterns_text, result_factor, rope_slack, setup_roles,
    stage_report, type_shares, world_judgement,
)
from zinro_learn.board import ROLES_11A as ROLES_11A_PKG

ROOT = Path(__file__).resolve().parent.parent
SMALL = {"人狼": 1, "狂人": 1, "占い師": 1, "霊能者": 1, "村人": 2}
ROLES_11A = {"人狼": 2, "狂人": 1, "占い師": 1, "霊能者": 1, "狩人": 1, "村人": 4}      # 11A(ダミーを除く10人)


def small_board(**kw) -> Board:
    board = Board(players=list("ABCDEF"), roles=dict(SMALL))
    for key, value in kw.items():
        setattr(board, key, value)
    return board


def brute_force(board: Board) -> list[dict]:
    """全部の役職の並べ方から、公開された情報に合うものを数える(board.py の関数は使わない、別の書き方)。"""
    seats = [role for role, n in board.roles.items() for _ in range(n)]
    out = []
    for perm in set(permutations(seats)):
        a = dict(zip(board.players, perm))
        ok = True
        for p, role in board.claims:
            ok &= a[p] in (role, "人狼", "狂人")
        ok &= all(a[p] != "人狼" for p in board.bitten)
        ok &= all(a[p] == "人狼" for p in board.wolf_co)
        for r in board.results:
            real = {"占い": "占い師", "霊能": "霊能者"}[r["kind"]]
            if a[r["player"]] == real:
                ok &= (a[r["target"]] == "人狼") == (r["color"] == "黒")
        if board.ongoing:                                   # まだ勝敗が決まっていない: 人狼が生きていて、人間より少ない
            gone = set(board.dead)
            wolves = sum(1 for p in board.players if a[p] == "人狼" and p not in gone)
            humans = sum(1 for p in board.players if a[p] != "人狼" and p not in gone)
            ok &= 0 < wolves < humans
        if ok:
            out.append(a)
    return out


class WorldCountTest(unittest.TestCase):
    def assert_same_count(self, board: Board):
        worlds = enumerate_worlds(board)
        self.assertEqual(sum(w.count for w in worlds), len(brute_force(board)))
        return worlds

    def test_claims_and_results_match_a_brute_force_count(self):
        board = small_board(
            claims=[("A", "占い師"), ("C", "占い師"), ("E", "霊能者")],
            results=[
                {"kind": "占い", "player": "A", "target": "B", "color": "白"},
                {"kind": "占い", "player": "C", "target": "D", "color": "黒"},
                {"kind": "霊能", "player": "E", "target": "D", "color": "黒"},
            ],
            executed=["D"],
        )
        worlds = self.assert_same_count(board)
        self.assertTrue(worlds)
        # D が処刑されて霊能が「黒」: 霊能が本物なら D は人狼。C の黒が当たり、C は本物(か、狂人の偶然)
        real_medium = [w for w in worlds if w.assign["E"] == "霊能者"]
        self.assertTrue(all(w.assign["D"] == "人狼" for w in real_medium))

    def test_bitten_players_are_not_wolves_and_a_wolf_co_is_a_wolf(self):
        board = small_board(claims=[("A", "占い師")], bitten=["F"], wolf_co=["B"])
        worlds = self.assert_same_count(board)
        self.assertTrue(all(w.assign["B"] == "人狼" and w.assign["F"] != "人狼" for w in worlds))

    def test_dead_and_unclaimed_players_get_the_remaining_roles(self):
        board = small_board(executed=["B"], bitten=["F"])
        worlds = self.assert_same_count(board)
        self.assertEqual({w.assign["F"] for w in worlds}, {"狂人", "占い師", "霊能者", "村人"})

    def test_a_game_that_is_still_going_has_a_wolf_alive_and_fewer_than_the_humans(self):
        # 人狼1人の小さな村で、処刑された人が人狼なら、そこで勝負は決まっている(続いているはずがない)
        board = small_board(executed=["D"], results=[{"kind": "霊能", "player": "E", "target": "D", "color": "黒"}], claims=[("E", "霊能者")])
        self.assertTrue(all(w.assign["D"] != "人狼" or w.assign["E"] != "霊能者" for w in enumerate_worlds(board)))
        board.ongoing = False
        self.assertTrue(any(w.assign["D"] == "人狼" and w.assign["E"] == "霊能者" for w in enumerate_worlds(board)))

    def test_no_world_when_the_facts_cannot_all_hold(self):
        # 占い師を名乗った1人だけが、同じ相手に白と黒の両方を出している: 本物ではありえないが、偽ならありうる
        board = small_board(
            claims=[("A", "占い師")],
            results=[{"kind": "占い", "player": "A", "target": "B", "color": "黒"}, {"kind": "占い", "player": "A", "target": "B", "color": "白"}],
        )
        worlds = enumerate_worlds(board)
        self.assertTrue(worlds and all(w.assign["A"] in ("人狼", "狂人") for w in worlds))
        # 狼COの人が、襲撃で死んだ(人狼は襲撃されない)
        self.assertEqual(enumerate_worlds(small_board(bitten=["B"], wolf_co=["B"])), [])


class TierTest(unittest.TestCase):
    def test_two_seers_and_one_medium_the_standard_is_real_wolf_real(self):
        """依頼者の話: 今の12A猫は、2-1なら真狼-真が定番。霊はたいてい真。"""
        rows = claim_patterns(2, 1)
        by_tier = {t: sorted({r["label"] for r in rows if r["tier"] == t}) for t in (3, 2, 1)}   # 名乗った人の入れ替えは、同じ組み合わせ
        self.assertEqual(by_tier[3], ["真狼-真"])
        self.assertEqual(by_tier[2], ["真狂-真"])
        self.assertEqual(by_tier[1], [])                              # ロケットCOなら、本物が名乗らない世界(霊の偽・占いの潜伏)は、ない
        self.assertIn("2-1: 定番: 真狼-真 | ありうる: 真狂-真 | まれ:", patterns_text())
        # ロケットCOでない一般の盤面では、霊に本物がいない(霊の偽)のは、まれ
        loose = claim_patterns(2, 1, rco=False)
        loose_tier = {t: sorted({r["label"] for r in loose if r["tier"] == t}) for t in (3, 2, 1)}
        self.assertNotIn("真狼-狼", loose_tier[3] + loose_tier[2])
        self.assertIn("真狼-狼", loose_tier[1])

    def test_three_seers_and_one_medium_the_common_case_has_a_madman_and_two_wolves_are_possible(self):
        """依頼者の話: 3-1 は、12A猫でも真狂狼がまだ多い。真狼狼もありうる。"""
        rows = claim_patterns(3, 1)
        by_tier = {t: sorted({r["label"] for r in rows if r["tier"] == t}) for t in (3, 2, 1)}
        self.assertEqual(by_tier[3], ["真狼狂-真"])
        self.assertEqual(by_tier[2], ["真狼狼-真"])
        weight: dict[str, float] = {}
        for r in rows:
            weight[r["label"]] = weight.get(r["label"], 0.0) + r["weight"]
        self.assertAlmostEqual(weight["真狼狂-真"] / weight["真狼狼-真"], 3.0)      # 真狂狼 7.5 : 真狼狼 2.5(依頼者の数字)
        reasons = {r["label"]: r["reasons"] for r in rows if r["tier"] == 2}
        self.assertEqual(reasons["真狼狼-真"], ("偽が人狼だけ(狂人が偽に出ない)",))
        self.assertIn("3-1: 定番: 真狼狂-真 | ありうる: 真狼狼-真 | まれ:", patterns_text())

    def test_the_composition_shares_match_the_users_numbers(self):
        """依頼者の数字: 2-1 のうち真狂は、いまの置き方(6%くらい)でよい。3-1 は、真狂狼 7.5 : 真狼狼 2.5。"""
        def weights(seers: int) -> dict[str, float]:
            out: dict[str, float] = {}
            for r in claim_patterns(seers, 1):
                out[r["label"]] = out.get(r["label"], 0.0) + r["weight"]
            return out
        w21 = weights(2)
        self.assertAlmostEqual(w21["真狂-真"] / (w21["真狂-真"] + w21["真狼-真"]), 0.0625, places=3)
        w31 = weights(3)
        self.assertAlmostEqual(w31["真狼狼-真"] / (w31["真狼狼-真"] + w31["真狼狂-真"]), 0.25)

    def test_with_one_fake_the_madman_is_possible_and_with_two_or_more_he_is_expected(self):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO))
        board.claims = [("A", "占い師"), ("B", "占い師"), ("K", "霊能者")]
        self.assertEqual(world_judgement(board, {"A": "占い師", "B": "人狼", "K": "霊能者"}), (3, ()))
        self.assertEqual(world_judgement(board, {"A": "占い師", "B": "狂人", "K": "霊能者"})[0], 2)
        board.claims.append(("C", "占い師"))
        self.assertEqual(world_judgement(board, {"A": "占い師", "B": "人狼", "C": "狂人", "K": "霊能者"}), (3, ()))
        self.assertEqual(world_judgement(board, {"A": "占い師", "B": "人狼", "C": "人狼", "K": "霊能者"})[0], 2)

    def test_a_lone_medium_is_real_in_the_standard_case(self):
        rows = claim_patterns(0, 1, rco=False)                        # ロケットCOでない一般の盤面
        self.assertEqual(sorted({r["label"] for r in rows if r["tier"] == 3}), ["なし-真"])
        self.assertEqual({r["label"] for r in rows if r["tier"] == 1}, {"なし-狼", "なし-狂"})

    def test_rocket_co_removes_the_worlds_where_the_real_seer_or_medium_hides(self):
        """依頼者の説明: RCO はロケットCO(一発言目の CO)。狐のない配役では強いので、約束事として潜伏は「ない」。"""
        self.assertEqual(claim_patterns(0, 1), [])                    # 占いの名乗りがない盤面は、ない
        self.assertEqual(claim_patterns(1, 0), [])
        self.assertIn("(占い・霊能の本物は、ロケットCO", patterns_text())
        self.assertNotIn("0-1:", patterns_text())
        board = claim_board(ROLES_12A_NEKO, "ABCDEFGHIJK", "AB", "K", [])
        worlds = enumerate_worlds(board)
        self.assertTrue(worlds and all(w.assign["K"] == "霊能者" for w in worlds))      # 霊の名乗りが1人なら、本物
        self.assertTrue(all("占い師" in (w.assign["A"], w.assign["B"]) for w in worlds))   # 本物の占いは、名乗った2人の中にいる
        board.rco = False
        self.assertTrue(any(w.assign["K"] != "霊能者" for w in enumerate_worlds(board)))

    def test_a_fake_black_that_hits_a_wolf_is_rare_and_explained(self):
        board = Board(players=list("ABCDEFGHIJK"), roles={"人狼": 3, "狂人": 1, "占い師": 1, "霊能者": 1, "狩人": 1, "猫又": 1, "村人": 3})
        board.claims = [("A", "占い師"), ("B", "占い師"), ("C", "霊能者")]
        board.results = [{"kind": "占い", "player": "A", "target": "D", "color": "黒"}]
        assign = {"A": "人狼", "B": "占い師", "C": "霊能者", "D": "人狼"}
        tier, reasons = world_judgement(board, assign)
        self.assertEqual(tier, 1)
        self.assertEqual(len(reasons), 1)
        self.assertIn("切り", reasons[0])
        assign["D"] = "村人"                                           # 偽の黒が村人に当たる(ふつうの偽の黒)
        self.assertEqual(world_judgement(board, assign), (3, ()))
        self.assertEqual(pattern_label(board, assign), "真狼-真")


def claim_board(roles: dict, players: str, seers: str, medium: str, results: list[dict], rco: bool = True) -> Board:
    """占いを名乗った人(seers)と、霊能を名乗った1人(medium)と、占いの初手の結果がある盤面。rco は、本物はロケットCOで名乗る(潜伏なし)。"""
    board = Board(players=list(players), roles=dict(roles), rco=rco)
    board.claims = [(p, "占い師") for p in seers] + [(medium, "霊能者")]
    board.results = [dict(kind="占い", first=True, **r) for r in results]
    return board


def shares_of(board: Board, worlds=None, **kw) -> dict[str, dict[str, float]]:
    worlds = enumerate_worlds(board, **kw) if worlds is None else worlds
    return {p: sh for _, p, sh in type_shares(board, worlds)}


class EnvironmentTreatmentTest(unittest.TestCase):
    """依頼者に聞いた、今の環境での扱い。重みの数字は仮なので、割合の大小と順序で確かめる。"""

    def neko(self, seers: str, results: list[dict]) -> Board:
        return claim_board(ROLES_12A_NEKO, "ABCDEFGHIJK", seers, "K", results)

    def test_a_first_move_counter_white_in_2_1_is_probably_a_wolf(self):
        board = self.neko("AB", [{"player": "A", "target": "B", "color": "白"}])
        worlds = enumerate_worlds(board)
        # 真狼のとき、本物は相手(人狼)に白を出せない。出せるのは、相手が狂人のとき(環境の問題)だけ
        self.assertFalse(any(w.assign["A"] == "占い師" and w.assign["B"] == "人狼" for w in worlds))
        self.assertTrue(any(w.assign["A"] == "占い師" and w.assign["B"] == "狂人" for w in worlds))
        a = shares_of(board, worlds)["A"]
        self.assertGreater(a["狼"], 0.5)
        self.assertGreater(a["狼"], 3 * a["真"])
        # 定番(真狼-真)の世界では、出した A は人狼
        standard = [w for w in worlds if w.tier == 3]
        self.assertTrue(standard and all(w.assign["A"] == "人狼" and w.assign["B"] == "占い師" for w in standard))

    def test_a_first_move_black_leans_real_whether_it_is_on_the_counter_or_on_grey(self):
        for target in ("B", "D"):                                         # 初手の対抗黒と、初手のグレーへの黒
            board = self.neko("AB", [{"player": "A", "target": target, "color": "黒"}])
            first = shares_of(board)["A"]["真"]
            self.assertGreater(first, 0.5, target)
            later = self.neko("AB", [{"player": "A", "target": target, "color": "黒"}])
            later.results[0]["first"] = False                              # 二手目以降は、癖を聞いていないので数えない
            self.assertGreater(first, shares_of(later)["A"]["真"] + 0.1, target)
            # 偽が初手に黒を出す割合が高いほど、真目は薄れる(人外の凸が最良手でない、という話が効いている)
            self.assertLess(shares_of(board, fake_black_first=0.5)["A"]["真"], first, target)

    def test_a_counter_black_in_3_1_is_quite_real_and_a_first_move_black_leans_real_everywhere(self):
        """依頼者の話: 3-1 の対抗黒は結構真目(狩人が、霊護衛でなく黒を出した占いの護衛を固定するまである。目安は本物の見込み7割台)。
        初手黒がとにかく真目多い環境。偽の初手の黒を 1.5割、3-1 の真狼狼を 2.5 にして、7割台に合わせた(依頼者の判断)。"""
        board = self.neko("ABC", [{"player": "A", "target": "B", "color": "黒"}])
        shares = shares_of(board)
        self.assertGreater(shares["A"]["真"], 0.7)
        self.assertLess(shares["A"]["真"], 0.8)
        self.assertGreater(shares["A"]["真"], 2 * shares["B"]["真"])                   # 黒を出された側は、本物であることが少ない
        self.assertLess(shares_of(board, fake_black_first=0.2)["A"]["真"], shares["A"]["真"])   # 偽の黒が多いほど、真目は薄れる
        for seers, target in (("AB", "B"), ("AB", "E"), ("ABC", "B")):                  # 2-1 の対抗黒・グレーへの黒と、3-1 の対抗黒
            b = self.neko(seers, [{"player": "A", "target": target, "color": "黒"}])
            self.assertGreater(shares_of(b)["A"]["真"], 0.5, (seers, target))
        for seers in ("AB", "ABC", "ABCD"):                                               # 名乗りが増えても、初手の黒は真目の方へ動く
            for target in ("B", "E"):
                first = self.neko(seers, [{"player": "A", "target": target, "color": "黒"}])
                later = self.neko(seers, [{"player": "A", "target": target, "color": "黒"}])
                later.results[0]["first"] = False
                self.assertGreater(shares_of(first)["A"]["真"], shares_of(later)["A"]["真"] + 0.1, (seers, target))

    def test_a_first_move_white_on_grey_does_not_lean_either_way(self):
        board = self.neko("AB", [{"player": "A", "target": "D", "color": "白"}])
        self.assertAlmostEqual(shares_of(board)["A"]["真"], 0.5, delta=0.15)

    def test_a_first_move_counter_white_is_eighty_percent_fake_even_in_the_best_board(self):
        """真狂狼-真は、対抗白を出した側が本物でありうる、いちばん有利な盤面(本物が白を出せる相手は狂人だけ)。そこでも8割は偽。"""
        board = self.neko("ABC", [{"player": "A", "target": "B", "color": "白"}])
        worlds = enumerate_worlds(board)
        best = [w for w in worlds if pattern_label(board, w.assign) == "真狼狂-真"]
        self.assertAlmostEqual(shares_of(board, best)["A"]["真"], 0.2)
        wolves_only = [w for w in worlds if pattern_label(board, w.assign) == "真狼狼-真"]      # 真狼狼では、本物は人狼に白を出せない
        self.assertTrue(wolves_only and all(w.assign["A"] != "占い師" for w in wolves_only))
        for seers in ("AB", "ABC", "ABCD"):                                                       # どの名乗りの数でも、8割以上が偽
            b = self.neko(seers, [{"player": "A", "target": "B", "color": "白"}])
            self.assertLessEqual(shares_of(b)["A"]["真"], 0.2, seers)

    def test_the_medium_is_mostly_real_on_every_board(self):
        for seers in ("AB", "ABC"):
            board = self.neko(seers, [{"player": "A", "target": "B", "color": "白"}])
            self.assertGreater(shares_of(board)["K"]["真"], 0.9, seers)

    def test_the_shares_of_each_claimant_add_up_to_one(self):
        board = self.neko("AB", [{"player": "A", "target": "D", "color": "黒"}])
        for _, p, sh in type_shares(board, enumerate_worlds(board)):
            self.assertAlmostEqual(sum(sh.values()), 1.0, msg=p)

    def test_the_result_factor_only_touches_a_fakes_first_seer_result(self):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO))
        board.results = [{"kind": "占い", "player": "A", "target": "D", "color": "黒", "first": True}]
        f = FAKE_BLACK_FIRST
        self.assertAlmostEqual(result_factor(board, {"A": "人狼", "D": "村人"}), f)                 # 人外の凸
        self.assertAlmostEqual(result_factor(board, {"A": "狂人", "D": "村人"}), f)
        self.assertEqual(result_factor(board, {"A": "人狼", "D": "人狼"}), 1.0)                    # 仲間への黒(切り)は段階で扱う
        self.assertEqual(result_factor(board, {"A": "占い師", "D": "人狼"}), 1.0)                   # 本物は、真偽の条件で決まる
        board.results[0]["color"] = "白"
        self.assertEqual(result_factor(board, {"A": "人狼", "D": "村人"}), 1.0)                     # 偽の白は、割り引かない
        board.results[0]["first"] = False                                                         # 二手目以降は、かけない
        board.results[0]["color"] = "黒"
        self.assertEqual(result_factor(board, {"A": "人狼", "D": "村人"}), 1.0)
        self.assertEqual(result_factor(board, {"A": "人狼", "D": "村人"}), 1.0)
        board.results[0].update(first=True, kind="霊能")                                           # 霊能の結果も、かけない
        self.assertEqual(result_factor(board, {"A": "人狼", "D": "村人"}), 1.0)

    def test_a_fake_that_never_charges_black_drops_those_worlds(self):
        board = self.neko("AB", [{"player": "A", "target": "D", "color": "黒"}])
        worlds = enumerate_worlds(board, fake_black_first=0.0)
        # 人狼でない人への偽の黒がなくなる。残る偽の黒は、人狼への黒(切り・偶然)だけ
        fake = [w for w in worlds if w.assign["A"] != "占い師"]
        self.assertTrue(fake and all(w.assign["D"] == "人狼" and w.tier == 1 for w in fake))


class ElevenAMemoTest(unittest.TestCase):
    """11A の確率論のまとめ(依頼者の持ち込み)の、組み合わせ論の数字を再現する。
    対抗白の矢印は、本物が出すなら 1通り(真→狂のみ)、偽が出すなら (n-1)^2 通り。出した側が本物の見込みは 1/(1+(n-1)^2)。"""

    LABELS = {2: "真狂-真", 3: "真狼狂-真", 4: "真狼狼狂-真"}              # 占いの名乗りの数 → 本物1人・狂人1人・残りは人狼、霊は本物

    def shares(self, n: int) -> dict[str, dict[str, float]]:
        players = "ABCDEFGHIJ"
        board = claim_board(ROLES_11A, players, players[:n], players[n], [{"player": "A", "target": "B", "color": "白"}], rco=False)
        worlds = enumerate_worlds(board, fake_black_first=0.0)              # 癖を入れない(純粋な組み合わせ論)
        keep = [w for w in worlds if pattern_label(board, w.assign) == self.LABELS[n]]
        self.assertTrue(keep)
        return shares_of(board, keep)

    def test_the_giver_is_real_with_probability_one_over_one_plus_n_minus_one_squared(self):
        for n, expected in ((2, 0.5), (3, 0.2), (4, 0.1)):
            self.assertAlmostEqual(self.shares(n)["A"]["真"], expected, msg=f"{n}-1")

    def test_the_3_1_posterior_matches_the_memo(self):
        s = self.shares(3)
        for player, (real, mad, wolf) in {"A": (0.2, 0.4, 0.4), "B": (0.4, 0.4, 0.2), "C": (0.4, 0.2, 0.4)}.items():
            self.assertAlmostEqual(s[player]["真"], real, msg=player)
            self.assertAlmostEqual(s[player]["狂"], mad, msg=player)
            self.assertAlmostEqual(s[player]["狼"], wolf, msg=player)

    def test_the_white_patterns_match_the_memo(self):
        """メモ 1-3: 真狂狼-真に固定したときの、白の出し方ごとの、真・狂・狼の見込み(%)。出し方は、A・B・C の順に、白を出した相手。"""
        players = "ABCDEFGHIJ"
        cases = {
            "相互白(A→B、B→A、C→グレー)": ([("A", "B"), ("B", "A"), ("C", "E")],
                                         {"A": (27.27, 50.00, 22.73), "B": (27.27, 50.00, 22.73), "C": (45.45, 0.00, 54.55)}),
            "一方向の鎖(A→B、B→C、C→グレー)": ([("A", "B"), ("B", "C"), ("C", "E")],
                                         {"A": (27.27, 22.73, 50.00), "B": (27.27, 50.00, 22.73), "C": (45.45, 27.27, 27.27)}),
            "グレー白2つと霊への白(A→グレー、B→グレー、C→霊)": ([("A", "E"), ("B", "F"), ("C", "D")],
                                         {"A": (31.25, 34.38, 34.38), "B": (31.25, 34.38, 34.38), "C": (37.50, 31.25, 31.25)}),
            "A→B、B→グレー、C→霊": ([("A", "B"), ("B", "F"), ("C", "D")],
                                         {"A": (21.43, 39.29, 39.29), "B": (35.71, 42.86, 21.43), "C": (42.86, 17.86, 39.29)}),
        }
        for name, (arrows, expected) in cases.items():
            board = claim_board(ROLES_11A, players, "ABC", "D", [{"player": p, "target": t, "color": "白"} for p, t in arrows], rco=False)
            worlds = [w for w in enumerate_worlds(board, fake_black_first=0.0) if pattern_label(board, w.assign) == self.LABELS[3]]
            shares = shares_of(board, worlds)
            for player, (real, mad, wolf) in expected.items():
                for kind, expect in (("真", real), ("狂", mad), ("狼", wolf)):                  # メモの値は、小数第2位までの丸め
                    self.assertAlmostEqual(shares[player][kind] * 100, expect, delta=0.006, msg=f"{name} {player} {kind}")

    def test_a_white_on_the_medium_leans_real_because_a_white_on_grey_is_slightly_fake(self):
        """メモ 1-3: 「霊に白=真目が高い」。理由は、グレー白が少し偽寄りだから(本物はグレーで人狼を引くと黒になる)。"""
        players = "ABCDEFGHIJ"
        board = claim_board(ROLES_11A, players, "ABC", "D", [
            {"player": "A", "target": "E", "color": "白"}, {"player": "B", "target": "F", "color": "白"}, {"player": "C", "target": "D", "color": "白"}], rco=False)
        worlds = [w for w in enumerate_worlds(board, fake_black_first=0.0) if pattern_label(board, w.assign) == self.LABELS[3]]
        shares = shares_of(board, worlds)
        self.assertGreater(shares["C"]["真"], shares["A"]["真"])
        self.assertAlmostEqual(shares["A"]["真"], shares["B"]["真"])

    def test_a_mutually_white_pair_always_has_a_madman(self):
        players = "ABCDEFGHIJ"
        board = claim_board(ROLES_11A, players, "ABC", "D", [
            {"player": "A", "target": "B", "color": "白"}, {"player": "B", "target": "A", "color": "白"}], rco=False)
        worlds = enumerate_worlds(board, fake_black_first=0.0)
        keep = [w for w in worlds if pattern_label(board, w.assign) == self.LABELS[3]]
        self.assertTrue(keep and all("狂人" in (w.assign["A"], w.assign["B"]) for w in keep))


class RopeTest(unittest.TestCase):
    def test_how_many_misses_the_village_can_afford(self):
        self.assertEqual(rope_slack(11, 3), 2)      # 昼1の12A: 外せるのは2回。3回目を外すと、人狼3・人間3で負け
        self.assertEqual(rope_slack(9, 2), 2)
        self.assertEqual(rope_slack(7, 1), 2)
        self.assertEqual(rope_slack(3, 1), 0)       # 3人・人狼1: 1回外すと、人狼1・人間1で負け
        self.assertEqual(rope_slack(7, 0), 0)

    def test_hanging_a_wolf_leaves_a_board_with_the_slack(self):
        self.assertEqual(next_hang_line(9, 2), {"alive": 7, "wolves": 1, "slack": 2, "win": False})
        self.assertTrue(next_hang_line(7, 1)["win"])


class Log17BoardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = load_record(ROOT / "knowledge/boards/log17.json")

    def test_the_record_has_no_real_names_and_every_event_belongs_to_a_stage(self):
        stages = len(self.record["stages"])
        self.assertTrue(all(0 <= e["stage"] < stages for e in self.record["events"]))
        self.assertEqual(sorted(self.record["players"]), list("CDEFGHIJKLM"))

    def test_the_truth_fits_the_public_facts_at_every_stage(self):
        for i in range(len(self.record["stages"])):
            board = board_at(self.record, i)
            truth = {p: self.record["truth"][p] for p in board.key_players()}
            self.assertTrue(any(w.assign == truth for w in enumerate_worlds(board)), f"段階 {i}")

    def test_the_standard_reading_chains_after_the_medium_reports(self):
        """昼2の朝: 霊能(本物)の結果で、M が人狼と分かり、L の黒が当たり。定番の世界では、L が真、D が狼。"""
        board = board_at(self.record, 1)
        worlds = enumerate_worlds(board)
        standard = confirmed(board, worlds, 3)
        self.assertEqual(sorted(standard["黒"]), ["D", "M"])
        self.assertEqual(sorted(standard["白"]), ["J", "L"])
        self.assertEqual(confirmed(board, worlds, 2)["黒"], ["M"])      # 狂人の偽を入れると、D が狂人の世界が残る

    def test_a_cut_black_takes_the_actual_game_out_of_the_standard_reading(self):
        tiers = []
        for i in range(len(self.record["stages"])):
            board = board_at(self.record, i)
            truth = {p: self.record["truth"][p] for p in board.key_players()}
            tiers.append(world_judgement(board, truth)[0])
        self.assertEqual(tiers, [3, 3, 1, 1, 1])                       # 昼2に D が仲間 F に黒を出して(切り)、まれになった

    def test_the_report_names_the_stage_the_standard_world_and_the_rope(self):
        text = stage_report(self.record, 1)
        self.assertIn("[定番] 真狼-真: D=狼 L=真 / J=真", text)
        self.assertIn("外せる回数 2(縄数 3)", text)
        self.assertIn("実際: 真狼-真、定番", text)

    def test_the_first_result_of_each_claimant_is_marked_as_the_first_move(self):
        board = board_at(self.record, 4)
        firsts = {(r["player"], r["target"]): r["first"] for r in board.results}
        self.assertEqual(firsts, {("D", "H"): True, ("L", "M"): True, ("J", "M"): True, ("D", "F"): False, ("J", "D"): False})

    def test_the_first_move_black_makes_the_real_seer_the_likelier_one_at_the_start(self):
        """昼1: D は H に白(初手)、L は M に黒(初手のグレーへの黒)。L が真の見込みの方が高い。実際も L が真。"""
        board = board_at(self.record, 0)
        shares = shares_of(board)
        self.assertGreater(shares["L"]["真"], shares["D"]["真"])
        self.assertGreater(shares["D"]["狼"], shares["L"]["狼"])
        self.assertIn("名乗った人の種類の見込み", stage_report(self.record, 0))

    def test_no_shares_are_shown_when_only_rare_worlds_remain(self):
        self.assertIn("まれだけなので、出さない", stage_report(self.record, 4))

    def test_unknown_event_kind_is_refused(self):
        record = json.loads(json.dumps(self.record))
        record["events"].append({"stage": 0, "t": "???"})
        with self.assertRaises(ValueError):
            board_at(record, 0)


class Log16BoardTest(unittest.TestCase):
    """占い入りの6A(人狼1・占い師1・村人3。霊能者なし)でも、同じ道具で盤面を整理できる。"""

    @classmethod
    def setUpClass(cls):
        cls.record = load_record(ROOT / "knowledge/boards/log16.json")

    def test_the_truth_fits_at_every_stage_and_a_lone_claim_is_the_real_seer_in_the_standard_case(self):
        for i in range(len(self.record["stages"])):
            board = board_at(self.record, i)
            truth = {p: self.record["truth"][p] for p in board.key_players()}
            worlds = enumerate_worlds(board)
            self.assertTrue(any(w.assign == truth for w in worlds), f"段階 {i}")
            standard = confirmed(board, worlds, 3)
            self.assertIn("D", standard["白"])                      # 名乗りが1人だけなら、定番では本物

    def test_an_executed_player_is_white_when_the_game_goes_on(self):
        board = board_at(self.record, 1)                             # 人狼は1人。E が処刑されても勝負が続いた
        worlds = enumerate_worlds(board)
        self.assertIn("E", confirmed(board, worlds, 1)["白"])
        shares = marginals(board, worlds)                            # A と F は灰。残る人狼1人は、2人のどちらか
        self.assertAlmostEqual(shares["A"]["人狼"], 0.5)
        self.assertAlmostEqual(shares["F"]["人狼"], 0.5)

    def test_grey_narrowing_checks_the_worst_order(self):
        self.assertFalse(narrowing_wins(7, 1, 0, 5))                 # 灰5人: 外れが4回続くと負ける
        self.assertTrue(narrowing_wins(7, 1, 0, 3))
        self.assertTrue(narrowing_wins(5, 1, 1, 0))                  # 確定黒を吊れば終わり
        self.assertFalse(narrowing_wins(11, 3, 0, 10))


class SetupAndRandomWhiteTest(unittest.TestCase):
    """10A狩・11A(依頼者: 比較的簡単な配役。人狼online では、基本的に初日に白が出る環境=白ランオンでやる)。"""

    def test_the_setups_name_the_role_tables_and_the_random_white_promise(self):
        self.assertEqual(set(SETUPS), {"12a-neko", "11a", "10a-kari"})
        self.assertEqual(ROLES_11A_PKG, ROLES_11A)                                    # 11A のメモ(`prob_11a.md`)の配役: 人狼2・占い1・霊能1・狩人1・狂人1・村人4(ダミーを除く)
        self.assertEqual(sum(ROLES_10A_KARI.values()), 9)                              # 10A狩: ダミーを除いて9人(推測。11A から村人が1人少ない)
        self.assertEqual(ROLES_10A_KARI["人狼"], 2)
        self.assertFalse(SETUPS["12a-neko"].random_white)                              # 12A猫は、ランオフ(占い師が初日の相手を選ぶ)
        self.assertTrue(SETUPS["11a"].random_white and SETUPS["10a-kari"].random_white)
        self.assertLess(SETUPS["11a"].fake_black_first, SETUPS["12a-neko"].fake_black_first)
        self.assertEqual(SETUPS["11a"].fake_black_first, FAKE_BLACK_FIRST_RANDOM_WHITE)

    def test_make_board_puts_the_seers_first_and_the_medium_last_and_the_dummy_after_everyone(self):
        board = make_board("11a", 3, [dict(player="A", target="D", color="白")])
        self.assertEqual(board.players, list("ABCDEFGHIJ") + [DUMMY])                  # 参加者10人 + ダミー(頭数は11)
        self.assertEqual(board.dummy, DUMMY)
        self.assertEqual(board.roles, {**ROLES_11A, "村人": 5})                          # 山は、ダミーの分の村人を足した11枚(依頼者: 頭数にダミーを数えて、11A は村人5)
        self.assertEqual(board.claims, [("A", "占い師"), ("B", "占い師"), ("C", "占い師"), ("J", "霊能者")])
        self.assertTrue(board.random_white and board.rco)
        self.assertEqual(board.results, [{"kind": "占い", "first": True, "player": "A", "target": "D", "color": "白"}])
        kari = make_board("10a-kari", 2)
        self.assertEqual(kari.players, list("ABCDEFGHI") + [DUMMY])                     # 10A狩: 参加者9人 + ダミー。山の村人は4(依頼者の訂正)
        self.assertEqual(kari.roles["村人"], 4)
        self.assertEqual(sum(kari.roles.values()), 10)
        neko = make_board("12a-neko", 2)
        self.assertEqual((neko.players[-1], neko.claims[-1], neko.random_white, neko.fake_black_first, neko.dummy), ("K", ("K", "霊能者"), False, FAKE_BLACK_FIRST, None))
        self.assertTrue(make_board("12a-neko", 2, random_white=True).random_white)    # 約束事を上書きできる
        plain = make_board("11a", 2, missing=False)
        self.assertEqual((plain.dummy, plain.players, plain.roles), (None, list("ABCDEFGHIJ"), ROLES_11A))                 # 役欠けなし: ダミーは村人で、参加者10人ぶんの山
        self.assertEqual(make_board("12a-neko", 2, missing=True).roles["村人"], 4)
        self.assertEqual(setup_roles("10a-kari"), ({**ROLES_10A_KARI, "村人": 4}, True))
        with self.assertRaises(ValueError):
            make_board("10a-kari", 9)

    def test_a_first_day_black_cannot_come_from_the_real_seer_under_random_white(self):
        black = [dict(player="A", target="C", color="黒")]
        on = enumerate_worlds(make_board("11a", 2, black, missing=False))
        self.assertTrue(on)
        self.assertTrue(all(w.assign["A"] != "占い師" for w in on))                    # 黒を出した A は、必ず偽
        self.assertTrue(all(w.assign["B"] == "占い師" for w in on))                    # 役欠けなしなら、もう一方の B が本物
        shares = shares_of(make_board("11a", 2, black, missing=False), on)
        self.assertEqual(shares["B"]["真"], 1.0)
        self.assertEqual(shares["A"]["真"], 0.0)
        off = enumerate_worlds(make_board("11a", 2, black, random_white=False, missing=False))
        self.assertTrue(any(w.assign["A"] == "占い師" for w in off))                   # ランオフなら、本物の黒もありうる
        missing = enumerate_worlds(make_board("11a", 2, black))                        # 役欠けあり: 占いが欠けていれば、B も偽でありうる
        self.assertTrue(all(w.assign["A"] != "占い師" for w in missing))
        self.assertTrue(any(w.assign["B"] != "占い師" for w in missing))
        self.assertGreater(shares_of(make_board("11a", 2, black), missing)["B"]["真"], 0.9)

    def test_only_the_first_result_is_pinned_to_white(self):
        later = [dict(player="A", target="C", color="黒", first=False)]
        board = make_board("11a", 2, later)
        self.assertTrue(any(w.assign["A"] == "占い師" for w in enumerate_worlds(board)))   # 二手目以降の黒は、本物でも出る

    def test_white_results_are_the_same_with_or_without_random_white(self):
        white = [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")]
        on = enumerate_worlds(make_board("11a", 2, white))
        off = enumerate_worlds(make_board("11a", 2, white, random_white=False))
        self.assertEqual(sorted(sorted(w.assign.items()) for w in on), sorted(sorted(w.assign.items()) for w in off))

    def test_the_fake_black_weight_follows_the_board_unless_given(self):
        board = make_board("11a", 2, [dict(player="A", target="C", color="黒", first=True)], random_white=False)
        fake_world = {"A": "人狼", "B": "占い師", "C": "村人"}
        self.assertAlmostEqual(result_factor(board, fake_world), FAKE_BLACK_FIRST_RANDOM_WHITE)       # 盤面の数字(11A は 0.05)
        self.assertAlmostEqual(result_factor(board, fake_world, 0.3), 0.3)                          # 渡せば、そちらが先
        self.assertAlmostEqual(result_factor(make_board("12a-neko", 2, [dict(player="A", target="C", color="黒")]), fake_world), FAKE_BLACK_FIRST)

    def test_a_record_names_its_setup(self):
        record = {"players": list("ABCDEFGHIJ"), "setup": "11a", "stages": [{"name": "昼1"}],
                  "events": [{"stage": 0, "t": "co", "player": "A", "role": "占い師"}, {"stage": 0, "t": "co", "player": "B", "role": "占い師"},
                             {"stage": 0, "t": "co", "player": "J", "role": "霊能者"},
                             {"stage": 0, "t": "result", "kind": "占い", "player": "A", "target": "C", "color": "黒"}]}
        board = board_at(record, 0)
        self.assertEqual(board.roles, setup_roles("11a")[0])                            # 役欠けあり: ダミーの分の村人を足した山
        self.assertEqual((board.dummy, board.players[-1]), (DUMMY, DUMMY))
        self.assertTrue(board.random_white)
        self.assertTrue(all(w.assign["A"] != "占い師" for w in enumerate_worlds(board)))
        plain = board_at({**record, "missing": False}, 0)                                # 記録で、役欠けなしにもできる
        self.assertEqual((plain.dummy, plain.roles), (None, ROLES_11A))
        old = board_at(load_record(ROOT / "knowledge/boards/log17.json"), 0)               # setup のない記録は、12A猫のまま
        self.assertEqual(old.roles, ROLES_12A_NEKO)
        self.assertFalse(old.random_white)

    def test_the_pattern_list_follows_the_role_table(self):
        text = patterns_text(roles=ROLES_11A, name="11A")
        self.assertTrue(text.startswith("11A: 占い-霊の名乗りの数"))
        self.assertIn("3-1: 定番: 真狼狂-真 | ありうる: 真狼狼-真", text)                    # 人狼2・狂人1: 偽が2人なら、狼と狂が定番
        self.assertNotIn("11A", patterns_text())                                          # 引数なしは、これまでどおり
        self.assertNotIn("0-1:", text)                                                    # 役欠けなし: 占いの名乗りが0人の盤面は、ない
        deck, missing = setup_roles("11a")
        text = patterns_text(roles=deck, name="11A", missing=missing)
        self.assertIn("0-1: 定番: なし-真", text)                                          # 役欠けあり: 占いが欠けて、だれも名乗らない盤面もある
        self.assertIn("1-1: 定番: 真-真 | ありうる: 狼-真、真-狼、狂-真、真-狂", text)       # 欠けていて、偽だけが名乗った盤面は、ありうる


class MissingRoleTest(unittest.TestCase):
    """役欠け(依頼者): 村人固定だと欠けなしになる。ダミー(初日犠牲者)は、人狼以外のどれにもなりうる。頭数にダミーを数える(10A狩は村人4)。"""

    def board(self, seers="AB", results=None):
        results = results if results is not None else [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")]
        return make_board("10a-kari", len(seers), results)

    def test_the_dummy_is_dead_from_the_start_and_takes_any_non_wolf_role(self):
        board = self.board()
        self.assertEqual(board.alive, list("ABCDEFGHI"))
        self.assertEqual(board.dead, [DUMMY])
        worlds = enumerate_worlds(board)
        roles = {w.assign[DUMMY] for w in worlds}
        self.assertEqual(roles, {"占い師", "霊能者", "狩人", "狂人", "村人"})              # 人狼以外の全てが欠けうる
        self.assertNotIn("人狼", roles)
        self.assertEqual(board.key_players()[-1], DUMMY)

    def test_the_dummy_role_follows_the_cards_in_the_deck(self):
        board = make_board("10a-kari", 0, [], rco=False)                                  # 名乗りも結果もない: 山からの無作為な1枚(人狼以外)
        board.claims = []
        worlds = enumerate_worlds(board)
        weight = {}
        for w in worlds:
            weight[w.assign[DUMMY]] = weight.get(w.assign[DUMMY], 0.0) + w.weight
        total = sum(weight.values())
        self.assertAlmostEqual(weight["村人"] / total, 4 / 8)                              # 人狼以外の8枚のうち、村人が4枚
        self.assertAlmostEqual(weight["占い師"] / total, 1 / 8)
        self.assertAlmostEqual(weight["狂人"] / total, 1 / 8)

    def test_a_missing_seer_leaves_only_fake_seers_and_is_a_plain_possibility(self):
        worlds = [w for w in enumerate_worlds(self.board()) if w.assign[DUMMY] == "占い師"]
        self.assertTrue(worlds)
        for w in worlds:
            self.assertTrue(all(w.assign[p] != "占い師" for p in "AB"))                  # 名乗った2人は、どちらも偽
            self.assertEqual(w.tier, 2)                                                   # ありうる
            self.assertIn(REASON_MISSING["占い師"], w.reasons)

    def test_a_real_seer_who_did_not_claim_is_still_excluded_by_rco(self):
        board = self.board()
        for w in enumerate_worlds(board):
            seer_holders = [p for p, r in w.assign.items() if r == "占い師"]
            self.assertTrue(seer_holders)                                                 # 占いの本物は、名乗った人か、ダミー(欠け)。灰に潜んでいる世界はない
            self.assertTrue(all(p in "AB" or p == DUMMY for p in seer_holders))
            self.assertEqual(len(w.left) and w.left["占い師"], 0)

    def test_without_the_dummy_nothing_changes(self):
        plain = make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")], missing=False)
        self.assertEqual(len(enumerate_worlds(plain)), 30)                               # 役欠けなしの数え方は、これまでどおり
        shares = shares_of(plain)
        self.assertAlmostEqual(shares["A"]["真"], 0.5)

    def test_the_confirmed_lists_never_name_the_dummy(self):
        board = self.board()
        worlds = enumerate_worlds(board)
        c = confirmed(board, worlds, 1)
        self.assertNotIn(DUMMY, c["白"] + c["黒"])

    def test_the_random_white_of_the_real_seer_makes_a_missing_seer_less_likely(self):
        results = [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")]

        def missing_share(random_white):
            board = make_board("10a-kari", 2, results, random_white=random_white)
            ws = enumerate_worlds(board)
            return sum(w.weight for w in ws if w.assign[DUMMY] == "占い師") / sum(w.weight for w in ws)

        self.assertLess(missing_share(True), missing_share(False))                       # 本物の白は、人狼でない人から無作為なので、その分だけ本物がいる世界の重みが大きい


if __name__ == "__main__":
    unittest.main()
