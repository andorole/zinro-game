import contextlib
import io
import random
import unittest
from unittest import mock

from zinro_learn.__main__ import main
from zinro_learn.board import DUMMY, FAKE_BLACK_FIRST, Board, ROLES_12A_NEKO, make_board
from zinro_learn.progress import (
    ALL_POLICIES, BITES, CAT_HIDE_SEERS_FIRST, CATS, COUNTER_CAT, COUNTER_CAT_BLACK, COUNTER_CAT_WOLF, ENCLOSE_NEXT, FAKE_BLACK_LATER, FAKE_CAT_FIRST, FAKE_CAT_PROACTIVE,
    FAKE_HUNTER_FIRST, GIDRA_CAT, GIDRA_HUNTER, GUARDS, HUNTER_BITE, HUNTER_COUNTER, HUNTER_NAME, HUNTERS, OPEN_CAT_BITE, POLICIES, POLICY_NAME, POSTERIOR, compare,
    compare_policies, compare_text, counter_cat, hit_rates, night_result, play, prepare, sample_world, win_rate,
    BITE_NAME, GUARD_NAME, HUNTER_BLACK_CO, HUNTER_GJ_CO, HUNTER_NARROW_CO, HUNTER_PAIR_READ, HUNTER_PAIR_WAIT, HUNTER_SCENES, LEAVE_CLAIMANT,
)


class FirstRng:
    """いつも先頭を選ぶ乱数(試合を決まった形で動かすための代役)。"""

    def choice(self, seq):
        return seq[0]

    def random(self):
        return 0.0

    def shuffle(self, seq):
        return None


class LastRng(FirstRng):
    """いつも末尾を選ぶ乱数(FirstRng の反対側)。"""

    def choice(self, seq):
        return seq[-1]


def neko(seers: str = "ABC", results=()) -> Board:
    board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
    board.claims = [(p, "占い師") for p in seers] + [("K", "霊能者")]
    board.results = [dict(kind="占い", first=True, **r) for r in results]
    return board


class EngineTest(unittest.TestCase):
    def test_a_tiny_village_matches_the_exact_win_rate(self):
        # 人狼1・村人3: 昼1に当たれば 1/4。外れると、夜に1人噛まれて人狼1・人間1で負け
        four = Board(players=list("ABCD"), roles={"人狼": 1, "村人": 3})
        self.assertAlmostEqual(win_rate(four, "grey", "grey", n=40000, seed=3)["rate"], 0.25, delta=0.012)
        # 人狼1・村人4: 1/5 + 4/5 × 1/3(2日目に残る3人から当てる)
        five = Board(players=list("ABCDE"), roles={"人狼": 1, "村人": 4})
        self.assertAlmostEqual(win_rate(five, "grey", "grey", n=40000, seed=3)["rate"], 1 / 5 + 4 / 5 * 1 / 3, delta=0.012)

    def test_the_same_seed_gives_the_same_result_and_the_worlds_are_shared_across_progressions(self):
        board = neko("ABC")
        first = win_rate(board, "roll_keep", "claim", n=2000, seed=7)
        again = win_rate(board, "roll_keep", "claim", n=2000, seed=7)
        self.assertEqual(first["rate"], again["rate"])
        shares = {p: {k: v["share"] for k, v in win_rate(board, p, "grey", n=2000, seed=7)["by_label"].items()} for p in POLICIES}
        self.assertEqual(len({tuple(sorted(s.items())) for s in shares.values()}), 1)     # 世界の引きは、進行によらず同じ

    def test_a_board_with_no_matching_world_is_refused(self):
        with self.assertRaises(ValueError):
            prepare(Board(players=list("ABCDEF"), roles={"人狼": 1, "占い師": 1, "村人": 4}, rco=True))        # 占いの名乗りがない(本物は名乗るはず)
        two_mediums = neko("AB")
        two_mediums.claims.append(("J", "霊能者"))
        with self.assertRaises(ValueError):
            prepare(two_mediums)

    def test_the_black_target_is_hanged_first_in_every_progression(self):
        board = neko("ABC", [{"player": "A", "target": "E", "color": "黒"}])
        prep = prepare(board)
        rng = random.Random(5)
        roles, _ = sample_world(prep, rng)
        for policy in POLICIES:
            trace: list = []
            play(prep, roles, policy, "grey", random.Random(1), trace)
            self.assertEqual(trace[0][:2], ("hang", "E"), policy)

    def _small(self):
        board = Board(players=list("ABCDEF"), roles={"人狼": 1, "占い師": 1, "霊能者": 1, "村人": 3}, rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("C", "霊能者")]
        prep = prepare(board)
        prep.wolf_prob.update({"A": 1.0, "B": 0.0})          # 順番を決める(A を先に吊る)
        roles = {"A": "占い師", "B": "人狼", "C": "霊能者", "D": "村人", "E": "村人", "F": "村人"}
        return prep, roles

    def test_the_medium_reports_the_hanged_color_next_morning_only_if_alive(self):
        prep, roles = self._small()
        trace: list = []
        self.assertTrue(play(prep, roles, "roll_stop", "grey", random.Random(2), trace, seer_results=False))
        self.assertEqual([t[0] for t in trace], ["hang", "bite", "report", "hang"])
        self.assertEqual(trace[2], ("report", "A", "白"))                 # 白が1つ出て、残る1人(B)は人狼と決まる
        self.assertEqual(trace[3][:2], ("hang", "B"))
        trace = []
        play(prep, roles, "roll_stop", "claim", random.Random(2), trace, seer_results=False)  # 名乗りを噛む: 霊能 C が噛まれて、結果が出ない
        self.assertEqual(trace[1][:2], ("bite", "C"))
        self.assertNotIn("report", [t[0] for t in trace])

    def test_a_roller_that_knows_a_seer_is_the_wolf_wins_at_once(self):
        board = Board(players=list("ABCDEF"), roles={"人狼": 1, "占い師": 1, "霊能者": 1, "村人": 3}, rco=True, wolf_co=["B"])
        board.claims = [("A", "占い師"), ("B", "占い師"), ("C", "霊能者")]
        for policy in ("roll", "roll_keep", "roll_stop"):
            self.assertEqual(win_rate(board, policy, "grey", n=200, seed=1)["rate"], 1.0, policy)
        self.assertLess(win_rate(board, "grey", "grey", n=2000, seed=1)["rate"], 0.6)

    def test_the_guard_blocks_a_bite_only_while_the_hunter_is_alive(self):
        board = Board(players=list("ABCDEF"), roles={"人狼": 1, "霊能者": 1, "狩人": 1, "村人": 3}, rco=True)
        board.claims = [("C", "霊能者")]
        prep = prepare(board)
        base = {"B": "村人", "C": "霊能者", "D": "村人"}
        # 灰を先頭から吊る。A が村人、狩人 E は生きている → 霊護衛が通る
        roles = {**base, "A": "村人", "E": "狩人", "F": "人狼"}
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, guard="medium")
        self.assertEqual(trace[1], ("guard", "C", ""))
        trace = []
        play(prep, roles, "grey", "claim", FirstRng(), trace)
        self.assertEqual(trace[1], ("bite", "C", ""))
        # 狩人が昼1に吊られると、護衛はない
        roles = {**base, "A": "狩人", "E": "村人", "F": "人狼"}
        trace = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, guard="medium")
        self.assertEqual(trace[1], ("bite", "C", ""))


class EnvGuardTest(unittest.TestCase):
    """環境の護衛(依頼者): 初手で黒が出ていれば、黒を出した占い。なければ、真目の占いか霊能。"""

    def _board(self, results=()):
        board = Board(players=list("ABCDEFGH"), roles={"人狼": 2, "占い師": 1, "霊能者": 1, "狩人": 1, "村人": 3}, rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("C", "霊能者")]
        board.results = [dict(kind="占い", first=True, **r) for r in results]
        roles = {"A": "占い師", "B": "人狼", "C": "霊能者", "D": "村人", "E": "人狼", "F": "狩人", "G": "村人", "H": "村人"}
        return prepare(board), roles

    def test_the_black_sayer_is_guarded_when_a_black_was_given(self):
        prep, roles = self._board([{"player": "A", "target": "E", "color": "黒"}])
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, guard="env")         # 黒先 E を吊る。狼は名乗りの先頭 A を噛む
        self.assertEqual(trace[0], ("hang", "E", "人狼"))
        self.assertEqual(trace[1], ("guard", "A", ""))
        trace = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, guard="medium")      # 霊護衛固定なら、A は守れずに噛まれる
        self.assertEqual(trace[1][:2], ("bite", "A"))

    def test_the_medium_is_guarded_when_no_black_was_given(self):
        board = Board(players=list("ABCDEF"), roles={"人狼": 1, "霊能者": 1, "狩人": 1, "村人": 3}, rco=True)
        board.claims = [("C", "霊能者")]
        prep = prepare(board)
        roles = {"A": "村人", "B": "村人", "C": "霊能者", "D": "村人", "E": "狩人", "F": "人狼"}
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, guard="env")
        self.assertEqual(trace[1], ("guard", "C", ""))

    def test_a_dead_black_sayer_is_replaced_by_the_medium_and_unknown_guards_are_refused(self):
        board = Board(players=list("ABCDEFGH"), roles={"人狼": 2, "占い師": 1, "霊能者": 1, "狩人": 1, "村人": 3}, rco=True)
        board.claims = [("B", "占い師"), ("C", "占い師"), ("A", "霊能者")]
        board.results = [dict(kind="占い", first=True, player="B", target="C", color="黒"),
                         dict(kind="占い", first=True, player="C", target="B", color="黒")]
        prep = prepare(board)
        prep.wolf_prob.update({"B": 1.0, "C": 0.0})                         # 昼1に、黒を出した B(偽)を吊る
        roles = {"A": "霊能者", "B": "人狼", "C": "占い師", "D": "村人", "E": "人狼", "F": "狩人", "G": "村人", "H": "村人"}
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, guard="env")
        self.assertEqual(trace[:2], [("hang", "B", "人狼"), ("guard", "A", "")])      # 黒を出した B は死んだので、霊能 A を守る
        trace = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, guard="blacksayer")
        self.assertEqual(trace[1][:2], ("bite", "A"))                       # 固定の護衛は、死んだ相手を守りつづけて、A を守れない
        with self.assertRaises(ValueError):
            play(prep, roles, "grey", "claim", FirstRng(), [], guard="???")


class SeerNightTest(unittest.TestCase):
    """占いの2日目以降の結果(夜に占い、翌朝に出す。村は、本物と見る占いの結果だけを信じる)。"""

    def _one_seer(self, wolf: str):
        board = Board(players=list("ABCDEF"), roles={"人狼": 1, "占い師": 1, "村人": 4}, rco=True)
        board.claims = [("A", "占い師")]
        prep = prepare(board)
        roles = {"A": "占い師", **{p: "村人" for p in "BCDEF"}}
        roles[wolf] = "人狼"
        return prep, roles

    def test_the_trusted_seers_black_is_hanged_the_next_day(self):
        prep, roles = self._one_seer("D")
        trace: list = []
        won = play(prep, roles, "grey", "grey", FirstRng(), trace)
        self.assertTrue(won)
        self.assertEqual(trace, [("hang", "B", "人間"), ("bite", "C", ""), ("result", "A", "D黒"), ("hang", "D", "人狼")])

    def test_a_seer_bitten_in_the_night_cannot_report(self):
        prep, roles = self._one_seer("F")
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace)               # 名乗りを噛む: 占い A が噛まれる
        self.assertEqual(trace[:2], [("hang", "B", "人間"), ("bite", "A", "")])
        self.assertNotIn("result", [t[0] for t in trace])
        trace = []
        play(prep, roles, "grey", "grey", FirstRng(), trace)                # 灰を噛む: A は生きて、白を出す
        self.assertEqual(trace[2], ("result", "A", "D白"))

    def test_a_white_given_by_the_trusted_seer_takes_that_grey_out_of_the_random_hang(self):
        prep, roles = self._one_seer("F")
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace)
        hangs = [t[1] for t in trace if t[0] == "hang"]
        self.assertEqual(hangs[:2], ["B", "E"])                             # D は白を貰ったので、次の吊りは先頭の D でなく E

    def test_a_fake_seer_that_the_village_trusts_leads_it_astray(self):
        board = Board(players=list("ABCDEF"), roles={"人狼": 1, "占い師": 1, "村人": 4}, rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師")]
        prep = prepare(board)
        prep.wolf_prob.update({"A": 0.0, "B": 1.0})                         # 村は A を本物と見る(実際は A が人狼で、B が本物)
        roles = {"A": "人狼", "B": "占い師", "C": "村人", "D": "村人", "E": "村人", "F": "村人"}
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace)
        self.assertEqual([t[:2] for t in trace[:5]], [("hang", "C"), ("bite", "D"), ("result", "A"), ("result", "B"), ("hang", "E")])
        self.assertEqual(trace[2], ("result", "A", "E黒"))                  # 偽の人狼は、人狼でない E に黒(FirstRng は、いつも黒を出す側に倒れる)
        self.assertEqual(trace[3], ("result", "B", "E白"))                  # 本物の白は、信じられない
        self.assertEqual(trace[4], ("hang", "E", "人間"))                   # 村は、偽の黒に従って、人間を吊る

    def test_a_fake_wolf_seer_encloses_a_teammate_on_the_next_night(self):
        """依頼者の話: 偽は、初手や次手で、仲間を囲うのが基本(身内切りは、戦術として強くない)。"""
        board = Board(players=list("ABCDEFG"), roles={"人狼": 2, "占い師": 1, "村人": 4}, rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師")]
        prep = prepare(board)
        prep.wolf_prob.update({"A": 0.0, "B": 1.0})                         # 村は A を本物と見る(実際は A が人狼)
        roles = {"A": "人狼", "B": "占い師", "C": "村人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼"}
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace)
        self.assertEqual([t[:2] for t in trace[:2]], [("hang", "C"), ("bite", "D")])
        self.assertIn(("result", "A", "G白"), trace)                         # 灰の仲間 G に白(囲い)
        trace = []
        with mock.patch("zinro_learn.progress.ENCLOSE_NEXT", 0.0):           # 囲わなければ、先頭の灰に、偽の黒
            play(prep, roles, "grey", "grey", FirstRng(), trace)
        self.assertIn(("result", "A", "E黒"), trace)
        self.assertGreater(ENCLOSE_NEXT, 0)

    def test_a_fakes_later_nights_are_mostly_white(self):
        """依頼者の話: 偽の二手目は、だいたい白。2日目以降の偽の黒の重みは、初手より小さい。"""
        self.assertLess(FAKE_BLACK_LATER, FAKE_BLACK_FIRST)
        rng = random.Random(3)
        blacks = sum(1 for _ in range(40000) if night_result("人狼", "村人", rng) == "黒")
        self.assertAlmostEqual(blacks / 40000, FAKE_BLACK_LATER / (1 + FAKE_BLACK_LATER), delta=0.006)
        self.assertLess(blacks / 40000, 0.1)

    def test_using_the_real_seers_nights_raises_the_win_rate(self):
        board = Board(players=list("ABCDEF"), roles={"人狼": 1, "占い師": 1, "村人": 4}, rco=True)
        board.claims = [("A", "占い師")]
        with_nights = win_rate(board, "grey", "grey", n=20000, seed=2)["rate"]
        without = win_rate(board, "grey", "grey", n=20000, seed=2, seer_results=False)["rate"]
        self.assertGreater(with_nights, without + 0.15)

    def test_the_night_result_colors_by_role(self):
        rng = FirstRng()                                                    # random() は 0.0: 黒を出す側
        self.assertEqual(night_result("占い師", "人狼", rng), "黒")
        self.assertEqual(night_result("占い師", "村人", rng), "白")
        self.assertEqual(night_result("人狼", "人狼", rng), "白")            # 仲間は白で守る
        self.assertEqual(night_result("人狼", "村人", rng), "黒")
        self.assertEqual(night_result("狂人", "人狼", rng), "黒")            # 狂人は、相手を知らない
        class NeverBlack(FirstRng):
            def random(self):
                return 0.99
        self.assertEqual(night_result("人狼", "村人", NeverBlack()), "白")


class CatTest(unittest.TestCase):
    """猫又(依頼者の説明): 吊られたら生存者からランダムに1人、噛まれたら人狼のうちランダムに1人を道連れにする。"""

    def test_a_hanged_cat_takes_a_random_survivor_along(self):
        prep = prepare(Board(players=list("ABCDEF"), roles={"人狼": 1, "猫又": 1, "村人": 4}))
        roles = {"A": "猫又", "B": "村人", "C": "村人", "D": "村人", "E": "村人", "F": "人狼"}
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False)
        self.assertEqual(trace[:2], [("hang", "A", "人間"), ("takealong", "B", "人間")])             # 村道連れ
        roles = {"A": "猫又", "B": "人狼", "C": "村人", "D": "村人", "E": "村人", "F": "村人"}
        trace = []
        self.assertTrue(play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False))
        self.assertEqual(trace, [("hang", "A", "人間"), ("takealong", "B", "人狼")])                   # 人狼道連れ: 人狼が全滅して、村の勝ち
        trace = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off")         # 力を数えなければ、道連れはない
        self.assertNotIn("takealong", [t[0] for t in trace])

    def test_a_bitten_cat_takes_a_wolf_along(self):
        prep = prepare(Board(players=list("ABCDEF"), roles={"人狼": 2, "猫又": 1, "村人": 3}))
        roles = {"A": "村人", "B": "猫又", "C": "村人", "D": "村人", "E": "人狼", "F": "人狼"}
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False)
        self.assertEqual([t[:2] for t in trace[:3]], [("hang", "A"), ("bite", "B"), ("takealong", "E")])

    def test_an_open_cat_is_neither_hanged_nor_bitten_while_other_candidates_remain(self):
        prep = prepare(Board(players=list("ABCDEF"), roles={"人狼": 1, "猫又": 1, "村人": 4}))
        roles = {"A": "猫又", "B": "村人", "C": "村人", "D": "村人", "E": "村人", "F": "人狼"}
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="open")
        self.assertEqual(trace[0][:2], ("hang", "B"))                       # 先頭の A(猫又)でなく、B
        self.assertEqual(trace[1][:2], ("bite", "C"))                       # 噛みも、A を避ける
        with self.assertRaises(ValueError):
            play(prep, roles, "grey", "grey", FirstRng(), [], cat="???")

    def test_wolves_sometimes_bite_an_open_cat_when_two_wolves_face_six_at_night(self):
        """依頼者の話: 人狼2人・夜に6人なら、猫又を噛めば一気に最終日に行ける。LW は絶対に噛めない。最近はあまり噛まない。"""
        prep = prepare(Board(players=list("ABCDEFG"), roles={"人狼": 2, "猫又": 1, "村人": 4}))
        roles = {"A": "村人", "B": "猫又", "C": "村人", "D": "村人", "E": "村人", "F": "人狼", "G": "人狼"}
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="open")           # FirstRng の random() は 0.0
        self.assertEqual([t[:2] for t in trace[:3]], [("hang", "A"), ("bite", "B"), ("takealong", "F")])
        trace = []
        with mock.patch("zinro_learn.progress.OPEN_CAT_BITE", 0.0):                                    # 噛まないなら、先頭の灰
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="open")
        self.assertEqual([t[:2] for t in trace[:2]], [("hang", "A"), ("bite", "C")])
        # 人狼が1人(LW)のときは、噛まない
        lw = prepare(Board(players=list("ABCDEFG"), roles={"人狼": 1, "猫又": 1, "村人": 5}))
        roles = {"A": "村人", "B": "猫又", "C": "村人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼"}
        trace = []
        play(lw, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="open")
        self.assertEqual([t[:2] for t in trace[:2]], [("hang", "A"), ("bite", "C")])
        self.assertLess(OPEN_CAT_BITE, 0.5)

    def test_the_cats_takealong_lets_grey_hangs_reach_wolves_among_the_seers_and_an_open_cat_helps(self):
        board = neko("ABC")
        with mock.patch("zinro_learn.progress.LEAVE_CLAIMANT", 0.0):                      # 名乗りを残す噛み方は別に見る(LeaveClaimantTest)
            self.assertLess(win_rate(board, "grey", "claim", n=6000, seed=5, cat="off")["rate"], 0.02)
        self.assertGreater(win_rate(board, "grey", "claim", n=6000, seed=5, cat="hidden")["rate"], 0.04)   # 道連れで、名乗りの中の狼にも当たる
        hidden = win_rate(board, "roll_stop", "grey", n=8000, seed=5, cat="hidden")["rate"]
        opened = win_rate(board, "roll_stop", "grey", n=8000, seed=5, cat="open")["rate"]
        self.assertGreater(opened, hidden + 0.05)                           # 対抗がいるとき、猫又は露出した方がよい(依頼者の話。この計算の向き)


class LateRng(FirstRng):
    """先頭を選ぶが、random() はいつも大きい値を返す(確率で決まる分かれ道で、起きない側に倒れる)。"""

    def random(self):
        return 0.99


class CounterCatTest(unittest.TestCase):
    """猫COに対抗猫が出たら、猫吊りが基本(依頼者)。黒を出された方、なければ先に出た方を吊る。道連れが起きたら本物、起きなければ偽が確定して、残る猫は放置。"""

    def _ten(self):
        # A が真猫。G・H が人狼(G が対抗猫になる)、I が狂人
        board = Board(players=list("ABCDEFGHIJ"), roles={"人狼": 2, "狂人": 1, "猫又": 1, "村人": 6})
        roles = {"A": "猫又", "B": "村人", "C": "村人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "人狼", "I": "狂人", "J": "村人"}
        return prepare(board), roles

    def test_the_earlier_cat_is_hanged_and_no_takealong_confirms_the_other_as_the_real_cat(self):
        prep, roles = self._ten()
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="counter")      # 対抗猫 G が先に出た(偽)
        self.assertEqual(trace[0], ("hang", "G", "人狼"))
        self.assertNotIn("takealong", [t[0] for t in trace[:3]])            # 道連れが起きない = 偽を吊れた
        self.assertEqual(trace[1][:2], ("bite", "B"))                       # 真猫 A は確定して、噛みも避ける
        self.assertEqual(trace[2][:2], ("hang", "C"))                       # 以後、A を吊らない(灰の先頭は B・C。B は噛まれた)

    def test_hanging_the_real_cat_takes_a_survivor_and_the_fake_cat_is_hanged_next(self):
        prep, roles = self._ten()
        trace: list = []
        with mock.patch("zinro_learn.progress.FAKE_CAT_FIRST", 0.0):                                  # 本物が先に出た: 先に出た方を吊ると本物
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="counter")
        self.assertEqual([t[:2] for t in trace[:4]], [("hang", "A"), ("takealong", "B"), ("bite", "C"), ("hang", "G")])   # 道連れで本物と分かり、偽の G を次に吊る

    def test_a_black_given_cat_is_hanged_first_even_with_a_counter_cat(self):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("K", "霊能者")]
        board.results = [dict(kind="占い", first=True, player="A", target="E", color="黒")]
        prep = prepare(board)
        roles = {"A": "人狼", "B": "占い師", "C": "人狼", "D": "狂人", "E": "猫又", "F": "村人", "G": "村人", "H": "村人", "I": "狩人", "J": "人狼", "K": "霊能者"}
        trace: list = []
        play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, cat="counter")
        self.assertEqual(trace[0], ("hang", "E", "人間"))                   # 真猫に黒が刺さった形: 黒先として吊られる
        self.assertEqual(trace[1][0], "takealong")                          # 道連れ

    def test_without_a_counter_cat_the_exposed_cat_is_left_alone_like_an_open_cat(self):
        prep, roles = self._ten()
        with mock.patch("zinro_learn.progress.COUNTER_CAT", 0.0):
            a: list = []
            play(prep, roles, "grey", "grey", FirstRng(), a, seer_results=False, cat="counter")
        b: list = []
        play(prep, roles, "grey", "grey", FirstRng(), b, seer_results=False, cat="open")
        self.assertEqual(a, b)

    def test_the_counter_cat_is_a_wolf_or_the_madman_who_has_not_claimed_a_seer(self):
        prep, roles = self._ten()
        alive = set(roles)
        self.assertEqual(counter_cat(roles, alive, set(), FirstRng()), ("G", True))                   # 先頭の人狼。先に出た
        self.assertEqual(counter_cat(roles, alive, set(), LateRng()), (None, False))                  # 出ない
        # 人狼の割合 COUNTER_CAT_WOLF(0.7)に対して 0.75 → 狂人
        class MadFirst(FirstRng):
            def __init__(self):
                self.values = iter([0.0, 0.75, 0.0])
            def random(self):
                return next(self.values)
        self.assertEqual(counter_cat(roles, alive, set(), MadFirst()), ("I", True))
        self.assertEqual(counter_cat(roles, alive, {"G", "H", "I"}, FirstRng()), (None, False))        # 人外がみな占いを名乗っていたら、猫の対抗は出ない
        rng = random.Random(4)
        draws = [counter_cat(roles, alive, set(), rng) for _ in range(20000)]
        shown = [d for d in draws if d[0]]
        self.assertAlmostEqual(len(shown) / 20000, COUNTER_CAT, delta=0.012)
        self.assertAlmostEqual(sum(1 for d in shown if d[0] in ("G", "H")) / len(shown), COUNTER_CAT_WOLF, delta=0.015)
        self.assertAlmostEqual(sum(1 for d in shown if d[1]) / len(shown), FAKE_CAT_FIRST, delta=0.015)

    def test_an_exposed_cat_with_a_counter_is_about_as_good_as_a_hidden_one_and_better_for_rollers_when_claims_are_bitten(self):
        board = neko("ABC")
        for policy in ("roll_keep", "roll_stop"):
            hidden = win_rate(board, policy, "claim", n=6000, seed=5, cat="hidden")["rate"]
            counter = win_rate(board, policy, "claim", n=6000, seed=5, cat="counter")["rate"]
            self.assertGreater(counter, hidden + 0.01, policy)              # 偽の猫を吊れる分、得をする(この計算の向き)

    def test_the_cat_names_cover_every_mode(self):
        self.assertEqual(set(CATS), {"off", "hidden", "open", "counter", "gidra"})


class GidraCatTest(unittest.TestCase):
    """猫又が出るのは、昼1だと、黒を刺されたとき(必ず出る)と、吊りを指定されたとき(単体で名乗る=ギドラ)(依頼者)。"""

    def _ten(self):
        # A が真猫。G・H が人狼(G が偽の猫になる)、I が狂人
        board = Board(players=list("ABCDEFGHIJ"), roles={"人狼": 2, "狂人": 1, "猫又": 1, "村人": 6})
        roles = {"A": "猫又", "B": "村人", "C": "村人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "人狼", "I": "狂人", "J": "村人"}
        return prepare(board), roles

    def test_a_designated_cat_comes_out_alone_and_the_village_picks_someone_else_when_no_counter_cat_appears(self):
        prep, roles = self._ten()
        trace: list = []
        with mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 0.0), mock.patch("zinro_learn.progress.COUNTER_CAT", 0.0):
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="gidra")
        self.assertEqual(trace[:3], [("cat", "A", "指定"), ("hang", "B", "人間"), ("bite", "C", "")])     # 先頭の灰 A は名乗って吊りを避け、B が吊られる
        self.assertNotIn("takealong", [t[0] for t in trace[:3]])
        hidden: list = []
        play(prep, roles, "grey", "grey", FirstRng(), hidden, seer_results=False, cat="hidden")
        self.assertEqual(hidden[:2], [("hang", "A", "人間"), ("takealong", "B", "人間")])                 # 隠れたままなら、そのまま吊られて道連れ

    def test_a_counter_cat_after_the_designated_cat_comes_out_makes_the_village_hang_the_earlier_real_cat(self):
        prep, roles = self._ten()
        trace: list = []
        with mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 0.0):
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="gidra")
        self.assertEqual([t[:2] for t in trace[:6]], [("cat", "A"), ("fakecat", "G"), ("hang", "A"), ("takealong", "B"), ("bite", "C"), ("hang", "G")])
        self.assertEqual(trace[1], ("fakecat", "G", "あとから出る"))
        # 道連れで本物と分かり、偽の G を次に吊る

    def test_a_black_given_cat_always_comes_out_and_is_hanged_first(self):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("K", "霊能者")]
        board.results = [dict(kind="占い", first=True, player="A", target="E", color="黒")]
        prep = prepare(board)
        roles = {"A": "人狼", "B": "占い師", "C": "人狼", "D": "狂人", "E": "猫又", "F": "村人", "G": "村人", "H": "村人", "I": "狩人", "J": "人狼", "K": "霊能者"}
        trace: list = []
        with mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 0.0):
            play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, cat="gidra")
        self.assertEqual([t[:2] for t in trace[:4]], [("cat", "E"), ("fakecat", "C"), ("hang", "E"), ("takealong", "A")])    # 名乗っても、黒先として吊られる(道連れは、先頭の生存者)
        self.assertEqual(trace[0], ("cat", "E", "黒"))

    def test_a_black_given_cat_draws_a_counter_cat_far_more_often_than_a_designated_one(self):
        """依頼者: 黒を刺された猫が出ると、人狼側は確定させたくないので、対抗が出て、真猫が貫通されるのが基本。"""
        self.assertGreater(COUNTER_CAT_BLACK, COUNTER_CAT)
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("K", "霊能者")]
        board.results = [dict(kind="占い", first=True, player="A", target="E", color="黒")]
        prep = prepare(board)
        roles = {"A": "人狼", "B": "占い師", "C": "人狼", "D": "狂人", "E": "猫又", "F": "村人", "G": "村人", "H": "村人", "I": "狩人", "J": "人狼", "K": "霊能者"}
        with mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 0.0), mock.patch("zinro_learn.progress.COUNTER_CAT", 0.0):
            trace: list = []
            play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, cat="gidra")
            self.assertIn(("fakecat", "C", "あとから出る"), trace)           # 指定なら出ない設定(0.0)でも、黒を刺された猫には対抗が出る
            with mock.patch("zinro_learn.progress.COUNTER_CAT_BLACK", 0.0):
                trace = []
                play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, cat="gidra")
                self.assertNotIn("fakecat", [t[0] for t in trace])

    def test_a_fake_cat_that_comes_out_first_makes_the_real_cat_expose_and_the_earlier_fake_is_hanged(self):
        prep, roles = self._ten()
        trace: list = []
        with mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 1.0):
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="gidra")
        self.assertEqual(trace[:4], [("fakecat", "G", "先に出る"), ("cat", "A", "対抗"), ("hang", "G", "人狼"), ("bite", "B", "")])
        self.assertNotIn("takealong", [t[0] for t in trace[:4]])             # 道連れが起きない = 偽を吊れた。真猫 A は確定して、噛みも避ける

    def test_an_undesignated_hidden_cat_stays_hidden(self):
        prep, roles = self._ten()
        roles = {**roles, "A": "村人", "B": "猫又"}                            # 猫は B。先頭の灰 A が吊られる
        trace: list = []
        with mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 0.0):
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="gidra")
        self.assertEqual(trace[0], ("hang", "A", "人間"))
        self.assertNotIn("cat", [t[0] for t in trace[:1]])
        with mock.patch("zinro_learn.progress.GIDRA_CAT", 0.0), mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 0.0):
            roles2 = {**roles, "A": "猫又", "B": "村人"}
            trace = []
            play(prep, roles2, "grey", "grey", FirstRng(), trace, seer_results=False, cat="gidra")
            self.assertEqual(trace[:2], [("hang", "A", "人間"), ("takealong", "B", "人間")])    # 名乗らなければ、隠れたまま吊られる

    def test_the_flows_give_about_the_stated_share_of_fake_first_pairs(self):
        """依頼者: 猫が2人のとき、先に出たのが偽の割合は6割くらい。先に出る偽(FAKE_CAT_PROACTIVE)と、指定・黒で出た真猫に対抗する偽の比で決まる(占いロラで確かめる)。"""
        board = neko("ABC")
        prep = prepare(board)
        rng = random.Random(8)
        first = later = 0
        for i in range(5000):
            roles, _ = sample_world(prep, rng)
            trace: list = []
            play(prep, roles, "roll_keep", "grey", random.Random(i), trace, cat="gidra")
            for t in trace:
                if t[0] == "fakecat":
                    first += t[2] == "先に出る"
                    later += t[2] == "あとから出る"
        self.assertGreater(first + later, 800)
        self.assertAlmostEqual(first / (first + later), 0.6, delta=0.12)
        self.assertEqual(GIDRA_CAT, 1.0)
        self.assertLess(FAKE_CAT_PROACTIVE, 0.5)


class HunterGidraTest(unittest.TestCase):
    """狩人のギドラ(依頼者): 本指定のタイミングで、狩もギドラCOをする。初手の回避は狩が良いことがある(狩貫通は初手にはしない)。"""

    def _eleven(self, **swap):
        # A が真の狩人。E・F・G が人狼、H が狂人、I が占い(名乗らない)、J が猫又、K が霊能(名乗る)
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=False)
        board.claims = [("K", "霊能者")]
        roles = {"A": "狩人", "B": "村人", "C": "村人", "D": "村人", "E": "人狼", "F": "人狼", "G": "人狼", "H": "狂人", "I": "占い師", "J": "猫又", "K": "霊能者"}
        roles.update(swap)
        return prepare(board), roles

    def test_a_designated_hunter_comes_out_and_the_village_picks_someone_else(self):
        prep, roles = self._eleven()
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra")
        self.assertEqual(trace[:3], [("hunter", "A", "指定"), ("hang", "B", "人間"), ("bite", "A", "")])      # 先頭の灰 A は名乗って吊りを避け、B が吊られる。名乗った A は噛まれる
        off: list = []
        play(prep, roles, "grey", "claim", FirstRng(), off, seer_results=False, cat="off")
        self.assertEqual(off[0], ("hang", "A", "人間"))                                   # 名乗らなければ、そのまま吊られる

    def test_a_hunter_who_has_come_out_is_bitten_only_with_the_stated_share(self):
        prep, roles = self._eleven()
        with mock.patch("zinro_learn.progress.HUNTER_BITE", 0.0):
            trace: list = []
            play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra")
        self.assertEqual(trace[:3], [("hunter", "A", "指定"), ("hang", "B", "人間"), ("bite", "K", "")])      # 噛みに来なければ、いつもどおり名乗りの霊能 K を噛む

    def test_a_hunter_who_has_come_out_is_not_hanged_while_other_greys_remain(self):
        prep, roles = self._eleven()
        with mock.patch("zinro_learn.progress.HUNTER_BITE", 0.0):
            trace: list = []
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra", guard="medium")
        hangs = [t[1] for t in trace if t[0] == "hang"]
        self.assertNotIn("A", hangs[:4])                                                 # 狩COを偽と割り切って吊る(狩貫通)は入れていない

    def test_a_wolf_designated_on_day_one_comes_out_as_a_fake_hunter_and_the_village_picks_someone_else(self):
        prep, roles = self._eleven(A="人狼", E="狩人")
        with mock.patch("zinro_learn.progress.HUNTER_COUNTER", 0.0):
            trace: list = []
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="fake")
        self.assertEqual(trace[:2], [("fakehunter", "A", "指定"), ("hang", "B", "人間")])                    # 初手は狩貫通をしない: 偽の A は吊られない
        gidra: list = []
        play(prep, roles, "grey", "grey", FirstRng(), gidra, seer_results=False, cat="off", hunter="gidra")
        self.assertEqual(gidra[0], ("hang", "A", "人狼"))                                # gidra は本物の狩人だけ: 人外は名乗らず、吊られる

    def test_the_real_hunter_can_come_out_against_the_fake_and_the_designated_fake_is_hanged(self):
        prep, roles = self._eleven(A="人狼", E="狩人")
        with mock.patch("zinro_learn.progress.HUNTER_PAIR_WAIT", 0.0), mock.patch("zinro_learn.progress.HUNTER_PAIR_READ", 1.0):      # 放置せず、発言で偽を見抜く
            trace: list = []
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="fake")     # FirstRng の random() は 0.0: 対抗が出る側
        self.assertEqual(trace[:3], [("fakehunter", "A", "指定"), ("hunter", "E", "対抗"), ("hang", "A", "人狼")])
        self.assertEqual(trace[3][0], "bite")                                            # 出た本物の狩人 E は、噛まれる(HUNTER_BITE)
        self.assertEqual(trace[3][1], "E")

    def test_when_two_hunters_have_come_out_the_village_hangs_the_fake_looking_one_or_leaves_both_for_a_day(self):
        """依頼者: 偽目を吊る。これも大体は発言から。ただし、即吊りでなく、一旦放置する進行を取る場合もある。"""
        prep, roles = self._eleven(A="人狼", E="狩人")

        def first_hang(wait: float, read: float):
            with mock.patch("zinro_learn.progress.HUNTER_PAIR_WAIT", wait), mock.patch("zinro_learn.progress.HUNTER_PAIR_READ", read):
                trace: list = []
                play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="fake")
            return next(t for t in trace if t[0] == "hang")

        self.assertEqual(first_hang(0.0, 1.0), ("hang", "A", "人狼"))                    # 発言で偽が見抜ける: 偽の A を吊る
        self.assertEqual(first_hang(0.0, 0.0), ("hang", "E", "人間"))                    # 見抜けない: 本物の E を吊ってしまう
        self.assertEqual(first_hang(1.0, 1.0), ("hang", "B", "人間"))                    # 放置する日: 2人は吊らず、別の人(先頭の灰 B)を吊る
        self.assertTrue(0 < HUNTER_PAIR_WAIT < 1 and 0.5 < HUNTER_PAIR_READ < 1)         # 仮の割合

    def _twelve(self, **swap):
        """12A猫(ランオフ・役欠けあり): A が偽の占い(人狼)、B が本物の占い、C が狩人、K が霊能。A が C に黒。"""
        board = make_board("12a-neko", 2, [dict(player="A", target="C", color="黒")])
        roles = {"A": "人狼", "B": "占い師", "C": "狩人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "人狼", "I": "狂人", "J": "猫又", "K": "霊能者", DUMMY: "村人"}
        roles.update(swap)
        return prepare(board), roles

    def test_a_hunter_who_is_given_a_black_comes_out_that_morning_and_the_black_is_found_false(self):
        """依頼者: 狩人が出るのは、指定されたらか、グレーが狭まったら詰む時か、黒を出された時。"""
        prep, roles = self._twelve()
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra")
        self.assertEqual(trace[:2], [("hunter", "C", "黒"), ("hang", "A", "人狼")])       # 黒を出された C は出て、黒先でも吊られない。単独のCOなので、黒は嘘: 黒を出した A は偽と分かり、先に吊られる
        with mock.patch("zinro_learn.progress.HUNTER_BLACK_CO", 0.0):
            trace = []
            play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra")
        self.assertEqual(trace[0], ("hang", "C", "人間"))                                 # 出なければ、黒先として吊られる
        trace = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra", reads=False)
        self.assertEqual(trace[0][:2], ("hunter", "C"))                                   # 村の読みなしでも、狩人は出て、吊られない
        self.assertNotEqual(next(t for t in trace if t[0] == "hang")[1], "C")

    def test_a_hunter_does_not_come_out_for_a_black_that_is_already_known_to_be_false(self):
        """白ランオン(10A狩・11A): 初日の黒は、その場で偽と分かる。狩人は出なくてよい。"""
        board = make_board("11a", 2, [dict(player="A", target="I", color="黒"), dict(player="B", target="D", color="白")])
        roles = {"A": "人狼", "B": "占い師", "C": "村人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "狂人", "I": "狩人", "J": "霊能者", DUMMY: "村人"}
        trace: list = []
        play(prepare(board), roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra")
        self.assertNotIn(("hunter", "I", "黒"), trace)

    def _seven(self, claims):
        board = Board(players=list("ABCDEFG"), roles={"人狼": 1, "占い師": 1, "霊能者": 1, "狩人": 1, "村人": 3}, rco=False)
        board.claims = claims
        roles = {"A": "人狼", "B": "占い師", "C": "霊能者", "D": "狩人", "E": "村人", "F": "村人", "G": "村人"}
        return prepare(board), roles

    def test_a_hunter_comes_out_when_leaving_the_grey_makes_the_grey_narrowing_win(self):
        """依頼者: グレーが狭まったら詰む時。自分が灰から抜けると、灰詰め(灰を端から吊れば、最悪の並びでも村が勝つ)が成り立つとき、出る。"""
        prep, roles = self._seven([("A", "占い師"), ("B", "占い師"), ("C", "霊能者")])
        calls: list = []

        def narrowing(alive, wolves, known_black, greys):
            calls.append((alive, wolves, known_black, greys))
            return greys <= 6                                                            # 灰が6人以下なら詰む(という境目。本物の数え方は board.py のテスト)

        observed: list = []
        with mock.patch("zinro_learn.progress.narrowing_wins", narrowing):
            trace: list = []
            play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra",
                 observer=lambda day, pb, worlds, wolf_p, target: observed.append((day, dict(pb.pinned))))
        self.assertEqual(calls[:2], [(7, 1, 0, 7), (7, 1, 0, 6)])                         # 名乗った占い・霊能も、確定していなければ灰に数える(盤面の報告の灰詰めと同じ)。D が抜けると6人
        self.assertEqual(trace[:2], [("hunter", "D", "詰み"), ("hang", "E", "人間")])      # 昼1の初めに D が出て、吊られない。E が吊られる
        self.assertEqual(observed[0], (1, {"D": "狩人"}))                                 # 盤面では、狩COした D は、狩人に決まった人
        with mock.patch("zinro_learn.progress.narrowing_wins", lambda alive, wolves, known_black, greys: greys <= 5):
            trace = []
            play(prep, roles, "grey", "claim", LastRng(), trace, seer_results=False, cat="off", hunter="gidra")
        self.assertEqual(trace[0], ("hang", "G", "人間"))                                 # 灰が6人では、まだ詰まない(D が抜けても、7→6): 出ない
        with mock.patch("zinro_learn.progress.narrowing_wins", narrowing), mock.patch("zinro_learn.progress.HUNTER_NARROW_CO", 0.0):
            trace = []
            play(prep, roles, "grey", "claim", LastRng(), trace, seer_results=False, cat="off", hunter="gidra")
        self.assertEqual(trace[0], ("hang", "G", "人間"))                                 # 割合が 0 なら、出ない

    def test_the_real_grey_narrowing_fits_a_late_game_so_the_hunter_rarely_comes_out_that_way(self):
        """本物の数え方では、12A猫の昼1・昼2に詰むことはない(生存11・人狼3は灰5人まで)。出るのは、終盤。"""
        from zinro_learn.board import narrowing_wins
        self.assertFalse(narrowing_wins(11, 3, 0, 6))
        self.assertTrue(narrowing_wins(11, 3, 0, 5))
        prep, roles = self._twelve()
        board = prep.board
        board.results = []                                                               # 黒なし
        trace: list = []
        play(prepare(board), roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra")
        self.assertNotIn("詰み", [t[2] for t in trace[:2] if t[0] == "hunter"])

    def test_a_hunter_comes_out_after_a_guard_success(self):
        """依頼者: GJがあった時も露出する事ある。護衛先が公開される(狼が噛みに来たので、人狼でない)。"""
        board = make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        roles = {"A": "人狼", "B": "占い師", "C": "村人", "D": "村人", "E": "狩人", "F": "村人", "G": "人狼", "H": "狂人", "I": "村人", "J": "霊能者", DUMMY: "村人"}
        trace: list = []
        seen: list = []

        def watch(day, pb, worlds, wolf_p, target):
            seen.append((day, dict(pb.pinned), list(pb.gj)))

        with mock.patch("zinro_learn.progress.HUNTER_NARROW_CO", 0.0):                    # 詰む時に出る動きは、ここでは見ない
            play(prepare(board), roles, "grey", "claim", LastRng(), trace, seer_results=False, cat="off", hunter="gidra", guard="medium", observer=watch)
        order = [t[:3] for t in trace if t[0] in ("hang", "guard", "hunter")][:3]
        self.assertEqual(order[1:], [("guard", "J", ""), ("hunter", "E", "GJ")])          # 名乗りの霊能 J を噛む夜に、霊能を護衛: GJ。翌朝、狩人が露出する
        self.assertEqual(seen[0], (1, {}, []))
        self.assertEqual(seen[1], (2, {"E": "狩人"}, ["J"]))                              # 護衛先 J が公開される
        with mock.patch("zinro_learn.progress.HUNTER_GJ_CO", 0.0):
            trace, seen = [], []
            play(prepare(board), roles, "grey", "claim", LastRng(), trace, seer_results=False, cat="off", hunter="gidra", guard="medium", observer=watch)
        self.assertNotIn("GJ", [t[2] for t in trace if t[0] == "hunter"])

    def test_the_hunter_scenes_are_the_stated_ones_and_the_flat_day_one_share_is_gone(self):
        self.assertEqual((HUNTER_BLACK_CO, HUNTER_NARROW_CO), (1.0, 1.0))                # 場面を聞いた(割合ではない): 黒を出された時、詰む時は、出る
        self.assertTrue(0 < HUNTER_GJ_CO <= 0.2)                                         # 仮。最新の答えは「基本的には指示されたら」なので、小さい
        self.assertEqual(HUNTER_SCENES, ("指定", "黒", "詰み", "GJ"))
        self.assertFalse(hasattr(make_board("11a", 2, []), "hunter_pre_co"))

    def test_the_scenes_can_be_chosen_and_a_hunter_without_the_designated_scene_is_hanged(self):
        prep, roles = self._eleven()
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra", hunter_scenes=("指定",))
        self.assertEqual(trace[:2], [("hunter", "A", "指定"), ("hang", "B", "人間")])
        trace = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra", hunter_scenes=("黒", "詰み", "GJ"))
        self.assertEqual(trace[0], ("hang", "A", "人間"))                                 # 指定の場面を外すと、指定されても出ない(潜伏): そのまま吊られる
        with self.assertRaises(ValueError):
            play(prep, roles, "grey", "claim", FirstRng(), [], cat="off", hunter="gidra", hunter_scenes=("指定", "???"))
        prep12, roles12 = self._twelve()
        trace = []
        play(prep12, roles12, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off", hunter="gidra", hunter_scenes=("指定",))
        self.assertEqual(trace[0], ("hang", "C", "人間"))                                 # 黒の場面を外すと、黒を出されても出ない

    def test_a_hunter_can_come_out_on_a_chosen_day_without_being_designated(self):
        """自発(出るタイミングの比較用): 昼 hunter_day の朝に出る。標準では使わない。"""
        prep, roles = self._eleven()
        trace: list = []
        play(prep, roles, "grey", "claim", LastRng(), trace, seer_results=False, cat="off", hunter="gidra", hunter_scenes=("指定",), hunter_day=2)
        kinds = [t[:3] for t in trace if t[0] in ("hunter", "hang")]
        self.assertEqual(kinds[0][0], "hang")                                            # 昼1は出ない(LastRng は末尾の灰 I を選ぶので、指定もされない)
        self.assertEqual(kinds[1], ("hunter", "A", "自発"))                              # 昼2の朝に出る
        late: list = []
        play(prep, roles, "grey", "claim", LastRng(), late, seer_results=False, cat="off", hunter="gidra", hunter_scenes=("指定",), hunter_day=0)
        self.assertNotIn("自発", [t[2] for t in late if t[0] == "hunter"])                # 0 なら出ない
        off: list = []
        play(prep, roles, "grey", "claim", LastRng(), off, seer_results=False, cat="off", hunter="off", hunter_day=1)
        self.assertNotIn("hunter", [t[0] for t in off])                                  # 狩人が名乗らない前提(off)では、自発もしない
        with self.assertRaises(ValueError):
            play(prep, roles, "grey", "claim", LastRng(), [], seer_results=False, cat="off", hunter="gidra", hunter_day=-1)

    def test_a_hunter_who_comes_out_on_a_guard_morning_names_the_guard_target(self):
        """GJの朝に出た狩人は、(出た理由によらず)護衛先を明かす。護衛先は人狼でない。"""
        board = make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        roles = {"A": "人狼", "B": "占い師", "C": "村人", "D": "村人", "E": "狩人", "F": "村人", "G": "人狼", "H": "狂人", "I": "村人", "J": "霊能者", DUMMY: "村人"}
        for scenes, day in ((("GJ",), 0), ((), 2)):
            seen: list = []
            trace: list = []
            with mock.patch("zinro_learn.progress.HUNTER_NARROW_CO", 0.0), mock.patch("zinro_learn.progress.HUNTER_GJ_CO", 1.0):
                play(prepare(board), roles, "grey", "claim", LastRng(), trace, seer_results=False, cat="off", hunter="gidra", guard="medium",
                     hunter_scenes=scenes, hunter_day=day, observer=lambda d, pb, ws, wp, t: seen.append((d, dict(pb.pinned), list(pb.gj))))
            self.assertEqual(seen[1], (2, {"E": "狩人"}, ["J"]), (scenes, day))            # どちらの理由でも、護衛先 J が公開される

    def test_a_real_hunter_who_comes_out_after_a_fake_has_the_earlier_one_hanged(self):
        prep, roles = self._eleven(A="人狼", D="狩人", E="村人")
        with mock.patch("zinro_learn.progress.HUNTER_COUNTER", 0.0), mock.patch("zinro_learn.progress.HUNTER_BITE", 0.0), \
                mock.patch("zinro_learn.progress.HUNTER_PAIR_WAIT", 0.0), mock.patch("zinro_learn.progress.HUNTER_PAIR_READ", 1.0):
            trace: list = []
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="fake")
        kinds = [t[:2] for t in trace]
        self.assertEqual(kinds[:3], [("fakehunter", "A"), ("hang", "B"), ("bite", "C")])      # 昼1: 偽の A は吊りを避け、B が吊られる。夜に C が噛まれる
        self.assertIn(("hunter", "D"), kinds)                                            # 昼2: 指定された本物の D が名乗る
        after = kinds[kinds.index(("hunter", "D")) + 1]
        self.assertEqual(after, ("hang", "A"))                                           # 2人の狩人が名乗ったので、先に出た偽の A を吊る

    def test_a_designated_hunter_always_comes_out_in_10a_and_11a_but_only_sometimes_in_12a(self):
        """依頼者: 10A狩・11A は、指定された狩人は当然狩COする(ギドラはない)。12A猫は、狩人も指定されたらギドラの「場合あり」(割合は仮)。"""
        from zinro_learn.board import SETUPS

        self.assertEqual((SETUPS["11a"].hunter_co, SETUPS["10a-kari"].hunter_co), (1.0, 1.0))
        self.assertIsNone(SETUPS["12a-neko"].hunter_co)
        self.assertEqual(make_board("11a", 2, []).hunter_co, 1.0)
        self.assertIsNone(make_board("12a-neko", 2, []).hunter_co)

        class Rng(FirstRng):
            def random(self):
                return 0.9                                                               # 0.7 は超え、1 は超えない

        def comes_out(board, roles):
            trace: list = []
            play(prepare(board), roles, "grey", "grey", Rng(), trace, seer_results=False, cat="off", hunter="gidra")
            return ("hunter", "C", "指定") in trace

        board11 = make_board("11a", 2, [dict(player="A", target="B", color="白"), dict(player="B", target="D", color="白")])
        roles11 = {"A": "人狼", "B": "占い師", "C": "狩人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "狂人", "I": "村人", "J": "霊能者", DUMMY: "村人"}
        self.assertTrue(comes_out(board11, roles11))                                     # 11A: 0.9 < 1 で、指定された狩人 C は名乗る
        board11.hunter_co = None                                                         # 12A猫と同じ扱い(GIDRA_HUNTER)にすると
        self.assertFalse(comes_out(board11, roles11))                                    # 0.9 >= 0.7 で、名乗らずに吊られる
        board11.hunter_co = 0.0
        self.assertFalse(comes_out(board11, roles11))

    def test_the_standard_modes_and_the_names(self):
        self.assertEqual(HUNTERS, ("off", "gidra", "fake"))
        self.assertEqual(set(HUNTER_NAME), set(HUNTERS))
        self.assertTrue(0.5 < GIDRA_HUNTER < 1)                                          # 仮(依頼者: 本指定のタイミングで、狩もギドラCOをする。ただし、指定されたらギドラの場合あり=いつもではない)
        self.assertTrue(0 < FAKE_HUNTER_FIRST < 1)                                       # 仮
        self.assertEqual((HUNTER_COUNTER, HUNTER_BITE), (1.0, 1.0))                      # 依頼者: 本物の狩人も対抗COする。名乗った狩人は、もちろん噛みに行く
        prep, roles = self._eleven()
        with self.assertRaises(ValueError):
            play(prep, roles, "grey", "grey", FirstRng(), [], hunter="???")

    def test_the_hunter_gidra_helps_the_village_by_keeping_the_guard_and_the_fake_hunter_saves_the_wolf_side_on_day_one(self):
        board = neko("AB")
        off = win_rate(board, "grey", "claim", n=12000, seed=1, guard="env", cat="gidra")["rate"]
        with mock.patch("zinro_learn.progress.HUNTER_GJ_CO", 0.0):                         # GJのあとの露出は別に見る(下)
            gidra = win_rate(board, "grey", "claim", n=12000, seed=1, guard="env", cat="gidra", hunter="gidra")["rate"]
        self.assertGreater(gidra, off + 0.04)                                            # 指定された狩人が名乗ると、吊られずに護衛が残る分、村が得をする
        with mock.patch("zinro_learn.progress.HUNTER_GJ_CO", 1.0):
            exposed = win_rate(board, "grey", "claim", n=12000, seed=1, guard="env", cat="gidra", hunter="gidra")["rate"]
        self.assertLess(exposed, gidra - 0.05)                                           # GJのたびに露出すると、名乗った狩人を狼が噛みに来て、護衛を失う分、村が損をする(護衛先が分かる得より大きい)
        prep = prepare(board)

        def wolf_side_first_hang(hunter: str) -> float:
            rng, hit, games = random.Random(3), 0, 1500
            for i in range(games):
                roles, _ = sample_world(prep, rng)
                trace: list = []
                play(prep, roles, "grey", "grey", random.Random(i), trace, seer_results=False, cat="off", hunter=hunter)
                first = next(t for t in trace if t[0] == "hang")
                hit += roles[first[1]] in ("人狼", "狂人")
            return hit / games

        with mock.patch("zinro_learn.progress.FAKE_HUNTER_FIRST", 1.0), mock.patch("zinro_learn.progress.HUNTER_COUNTER", 0.0):
            fake = wolf_side_first_hang("fake")
        plain = wolf_side_first_hang("gidra")
        self.assertGreater(plain, 0.2)                                                   # 灰8人のうち、人外は2〜3人
        self.assertLess(fake, plain * 0.65)                                              # 指定された人外が偽の狩人で避けると、昼1の吊りは人外に当たりにくい(半分ほど)


class MissingRoleProgressTest(unittest.TestCase):
    """役欠け(10A狩・11A): ダミー(初日犠牲者)の役職は人狼以外のどれか。欠けた役職は、いない前提で進行する。"""

    def _prep(self):
        board = make_board("10a-kari", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        return prepare(board)

    def _roles(self, **swap):
        # 参加者 A〜I とダミー。A が本物の占い、B が人狼で偽の占い、I が霊能(名乗る)、E・F が人狼 → B・E で人狼2は足りないので、F は村人
        roles = {"A": "占い師", "B": "人狼", "C": "村人", "D": "村人", "E": "人狼", "F": "村人", "G": "狩人", "H": "狂人", "I": "霊能者", DUMMY: "村人"}
        roles.update(swap)
        return roles

    def test_the_dummy_never_acts_or_dies_again(self):
        prep = self._prep()
        trace: list = []
        play(prep, self._roles(), "grey", "grey", FirstRng(), trace, cat="off")
        named = {t[1] for t in trace}
        self.assertNotIn(DUMMY, named)

    def test_a_dummy_hunter_means_no_guard(self):
        prep = self._prep()
        with_hunter, without = [], []
        with mock.patch("zinro_learn.progress.LEAVE_CLAIMANT", 0.0):                      # 名乗りを噛み続ける前提(残す噛み方は別に見る)
            play(prep, self._roles(), "grey", "claim", FirstRng(), with_hunter, seer_results=False, cat="off", guard="medium")
            play(prep, self._roles(G="村人", **{DUMMY: "狩人"}), "grey", "claim", FirstRng(), without, seer_results=False, cat="off", guard="medium")
        self.assertIn("guard", [t[0] for t in with_hunter])                              # 狩人が参加者にいれば、霊能 I への噛みを護衛が止める
        self.assertNotIn("guard", [t[0] for t in without])                               # 狩人が欠けていれば、護衛はない

    def test_a_fake_medium_has_no_usable_report(self):
        prep = self._prep()
        trace: list = []
        play(prep, self._roles(I="人狼", E="村人", **{DUMMY: "霊能者"}), "grey", "grey", FirstRng(), trace, seer_results=False, cat="off")
        self.assertNotIn("report", [t[0] for t in trace])                                # 霊が欠けて、名乗りが偽なら、報告は使えない
        real: list = []
        play(prep, self._roles(), "grey", "grey", FirstRng(), real, seer_results=False, cat="off")
        self.assertIn("report", [t[0] for t in real])

    def test_the_sampled_worlds_include_missing_roles_and_the_village_still_wins_sometimes(self):
        prep = self._prep()
        rng = random.Random(7)
        missing = {"占い師": 0, "霊能者": 0, "狩人": 0}
        n = 400
        for _ in range(n):
            roles, _ = sample_world(prep, rng)
            self.assertNotEqual(roles[DUMMY], "人狼")
            if roles[DUMMY] in missing:
                missing[roles[DUMMY]] += 1
        self.assertGreater(missing["狩人"], 20)                                           # 狩人の欠けは、1/8 ほどある(名乗りがない役職なので、減らない)
        self.assertGreater(missing["占い師"], 0)
        rate = win_rate(self_board(), "grey", "grey", n=1500, seed=3, guard="env", cat="off", hunter="gidra")["rate"]
        self.assertTrue(0.2 < rate < 0.95)

    def test_the_command_line_names_the_missing_role_rule(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["progress", "--setup", "10a-kari", "--seers", "2", "--result", "A:C:白", "--n", "200"])
        self.assertIn("10A狩・白ランオン・役欠けあり・2-1", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["progress", "--setup", "10a-kari", "--missing", "off", "--seers", "2", "--result", "A:C:白", "--n", "200"])
        self.assertNotIn("役欠けあり", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["board", "--patterns", "--setup", "10a-kari"])
        self.assertIn("0-1:", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["board", "--patterns", "--setup", "10a-kari", "--missing", "off"])
        self.assertNotIn("0-1:", out.getvalue())


def self_board():
    return make_board("10a-kari", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])


class BiteAndGuardModeTest(unittest.TestCase):
    """依頼者: 狼が噛むのは、占いか霊能。占いか霊能の各候補以外は噛まれない。護衛するのもどちらかでいい。"""

    def _game(self, **swap):
        board = make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        roles = {"A": "人狼", "B": "占い師", "C": "村人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "狂人", "I": "狩人", "J": "霊能者", DUMMY: "村人"}
        roles.update(swap)
        return prepare(board), roles

    def _first_night(self, bite, rng=None, **kw):
        prep, roles = self._game(**kw.pop("swap", {}))
        trace: list = []
        play(prep, roles, "grey", bite, rng or FirstRng(), trace, seer_results=False, cat="off", **kw)
        return next(t[:2] for t in trace if t[0] in ("bite", "guard")), trace

    def test_the_modes_are_named(self):
        self.assertEqual(BITES, ("grey", "claim"))                                       # 占い固定・霊能固定の噛み方は、読み違いだったので外した
        self.assertTrue(all(b in BITE_NAME for b in BITES) and "either" in GUARD_NAME and "either" in GUARDS)

    def test_the_claim_bite_goes_only_for_the_seer_and_medium_candidates(self):
        """各候補: 人狼でない占いの名乗りと霊能の名乗り。灰(C〜F、I)は噛まれない。"""
        picked = set()
        for i in range(60):
            night, _ = self._first_night("claim", random.Random(i))
            picked.add(night[1])
        self.assertEqual(picked, {"B", "J"})                                             # A は偽の占いだが人狼(仲間)なので噛まない
        picked = set()
        for i in range(60):
            night, _ = self._first_night("grey", random.Random(i))
            picked.add(night[1])
        self.assertTrue(picked.isdisjoint({"A", "B", "J", "G"}) and len(picked) >= 4)    # 灰を噛む(11A のメモの前提)は、候補を噛まない。実際とは違う

    def test_the_claim_bite_turns_to_the_grey_only_when_no_candidate_is_left(self):
        night, _ = self._first_night("claim", swap=dict(B="村人", C="占い師", J="人狼", G="村人", A="人狼", H="狂人"))
        # 占いの名乗り A(人狼)・B(村人の偽)、霊能の名乗り J(人狼): 人狼でない候補は B だけ
        self.assertEqual(night, ("bite", "B"))
        prep, roles = self._game(B="人狼", J="人狼", G="村人", C="占い師")
        roles["A"] = "人狼"
        trace: list = []
        play(prep, roles, "grey", "claim", FirstRng(), trace, seer_results=False, cat="off")     # 名乗りは A・B・J のすべてが人狼: 候補がいないので、灰を噛む
        bite = next(t[1] for t in trace if t[0] == "bite")
        self.assertNotIn(bite, {"A", "B", "J"})

    def test_an_unknown_bite_is_refused_before_the_game_starts(self):
        prep, roles = self._game()
        for bad in ("???", "seer", "medium"):
            with self.assertRaises(ValueError):
                play(prep, roles, "grey", bad, FirstRng(), [], cat="off")

    def test_the_either_guard_protects_the_believed_seer_or_the_medium_at_random(self):
        hidden = dict(swap=dict(E="狩人", I="村人"))                                      # 狩人は E(吊られない灰)。名乗らず、護衛する
        night, _ = self._first_night("claim", guard="either", hunter="gidra", **hidden)           # FirstRng: 先頭の候補 B を噛み、先頭(真目の占い B)を護衛: GJ
        self.assertEqual(night, ("guard", "B"))
        night, _ = self._first_night("claim", LastRng(), guard="either", hunter="gidra", **hidden)    # LastRng: 末尾の候補 J を噛み、末尾(霊能 J)を護衛: GJ
        self.assertEqual(night, ("guard", "J"))
        night, _ = self._first_night("claim", guard="env", hunter="gidra", **hidden)               # 環境の護衛: 霊能 J(黒なし)を護衛。B を噛む: 噛まれる
        self.assertEqual(night, ("bite", "B"))


class LeaveClaimantTest(unittest.TestCase):
    """依頼者: 夜1は初日犠牲者を噛む日(ダミー)。夜2は占いか霊能のどちらかを噛む(まほろ噛み)。夜3に、噛まなかった方を噛むとは限らない。
    どちらかが噛めた場合は、どちらかを残す方が寧ろ多い。"""

    def _game(self):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("K", "霊能者")]
        roles = {"A": "占い師", "B": "人狼", "C": "村人", "D": "人狼", "E": "人狼", "F": "狂人", "G": "狩人", "H": "猫又", "I": "村人", "J": "村人", "K": "霊能者"}
        return prepare(board), roles

    def _bites(self, rng):
        prep, roles = self._game()
        trace: list = []
        play(prep, roles, "grey", "claim", rng, trace, seer_results=False, cat="off")
        return [t[1] for t in trace if t[0] == "bite"]

    def test_the_first_bite_is_a_candidate_and_the_second_often_leaves_the_other_candidate(self):
        bites = self._bites(FirstRng())                                                  # FirstRng の random() は 0.0: 残す側
        self.assertEqual(bites[0], "A")                                                  # 夜2(依頼者の数え方)は候補 A
        self.assertNotIn(bites[1], {"A", "B", "K"})                                      # 夜3は、残りの候補 K を残して、灰を噛む
        bites = self._bites(LateRng())
        self.assertEqual(bites[:2], ["A", "K"])                                          # 残さない側: 残りの候補 K を噛む

    def test_the_stated_share_leaves_the_other_candidate_more_often_than_not(self):
        self.assertTrue(0.5 < LEAVE_CLAIMANT < 1)                                        # 「寧ろ多い」。割合は仮

    def test_before_a_candidate_has_died_the_wolves_always_bite_a_candidate(self):
        with mock.patch("zinro_learn.progress.LEAVE_CLAIMANT", 1.0):
            bites = self._bites(FirstRng())
        self.assertEqual(bites[0], "A")                                                  # 候補が1人も死んでいない夜は、割合によらず候補を噛む
        self.assertNotIn(bites[1], {"A", "B", "K"})                                      # 1 なら、あとはずっと残す

    def test_leaving_the_candidates_helps_a_village_that_only_hangs_the_grey(self):
        board = neko("ABC")
        kept = win_rate(board, "grey", "claim", n=6000, seed=5, cat="off")["rate"]
        with mock.patch("zinro_learn.progress.LEAVE_CLAIMANT", 0.0):
            bitten_all = win_rate(board, "grey", "claim", n=6000, seed=5, cat="off")["rate"]
        self.assertGreater(kept, bitten_all + 0.05)                                      # 名乗りが残ると、報告と結果が続いて、村に得
        self.assertLess(bitten_all, 0.02)

    def test_the_grey_bite_is_not_changed(self):
        board = neko("AB")
        with mock.patch("zinro_learn.progress.LEAVE_CLAIMANT", 0.0):
            a = win_rate(board, "grey", "grey", n=2000, seed=3, cat="off")["rate"]
        b = win_rate(board, "grey", "grey", n=2000, seed=3, cat="off")["rate"]
        self.assertEqual(a, b)


class PosteriorTest(unittest.TestCase):
    """尤度吊り(依頼者: 可能性の中でいちばん人狼がありそうな所を吊るのが人狼ゲーム)。毎朝、公開された情報に合う世界を数え直す。"""

    def _boards(self):
        return [
            ("12a-neko", make_board("12a-neko", 2, [dict(player="A", target="C", color="黒")]), dict(cat="gidra", hunter="gidra")),
            ("11a", make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")]), dict(cat="off", hunter="gidra")),
            ("10a-kari", make_board("10a-kari", 3, [dict(player="A", target="D", color="白"), dict(player="B", target="E", color="白"), dict(player="C", target="F", color="白")]),
             dict(cat="off", hunter="gidra")),
        ]

    def test_the_public_board_of_every_morning_contains_the_true_world(self):
        """吊り・夜の死亡・霊能の報告・占いの結果の積み上げ方が、シミュレーションと盤面の数え方で食い違っていないことの確かめ。"""
        for name, board, kw in self._boards():
            prep = prepare(board)
            rng = random.Random(5)
            days = set()
            for i in range(25):
                roles, _ = sample_world(prep, rng)
                seen: list = []

                def observe(day, pb, worlds, wolf_p, target):
                    keys = pb.key_players()
                    seen.append(any(all(w.assign[p] == roles[p] for p in keys) for w in worlds))
                    days.add(day)

                for policy in (POSTERIOR, "roll_keep"):
                    seen.clear()
                    play(prep, roles, policy, "claim", random.Random(i), guard="env", observer=observe, **kw)
                    self.assertTrue(seen and all(seen), (name, policy, i, seen))
            self.assertTrue({1, 2, 3} <= days, (name, days))                                # 昼2・昼3 の盤面も見ている

    def test_hunters_who_came_out_and_guard_successes_keep_the_true_world_in_the_public_board(self):
        """狩COした狩人(盤面では役職が決まる)と、GJの護衛先(人狼でない)を盤面に入れても、本当の世界が残る。"""
        board = make_board("10a-kari", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        prep = prepare(board)
        rng = random.Random(17)
        pinned_seen, gj_seen = 0, 0
        for i in range(60):
            roles, _ = sample_world(prep, rng)
            seen: list = []

            def observe(day, pb, worlds, wolf_p, target):
                keys = pb.key_players()
                seen.append(any(all(w.assign[p] == roles[p] for p in keys) for w in worlds))
                nonlocal pinned_seen, gj_seen
                pinned_seen += bool(pb.pinned)
                gj_seen += bool(pb.gj)

            for policy in (POSTERIOR, "roll_keep"):
                seen.clear()
                with mock.patch("zinro_learn.progress.HUNTER_GJ_CO", 1.0):
                    play(prep, roles, policy, "claim" if i % 2 else "grey", random.Random(i), guard="either", cat="off", hunter="gidra", observer=observe)
                self.assertTrue(seen and all(seen), (policy, i, seen))
        self.assertGreater(pinned_seen, 10)                                              # 狩COした盤面を、よく通った
        self.assertGreater(gj_seen, 5)                                                   # GJの護衛先が公開された盤面も通った

    def test_it_hangs_the_most_wolf_like_player_every_day(self):
        board = make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        prep = prepare(board)
        rng = random.Random(9)
        checked = 0
        for i in range(30):
            roles, _ = sample_world(prep, rng)

            def observe(day, pb, worlds, wolf_p, target):
                nonlocal checked
                self.assertAlmostEqual(wolf_p[target], max(wolf_p.values()), places=9)         # 吊り先の人狼の見込みが、生存者でいちばん高い
                self.assertEqual(set(wolf_p), set(pb.alive))
                checked += 1

            play(prep, roles, POSTERIOR, "grey", random.Random(i), guard="env", cat="off", rpp=False, observer=observe)
        self.assertGreater(checked, 60)

    def test_a_first_day_black_under_random_white_is_hanged_on_the_giver_by_the_numbers(self):
        board = make_board("11a", 2, [dict(player="A", target="C", color="黒"), dict(player="B", target="D", color="白")])
        prep = prepare(board)
        roles = {"A": "人狼", "B": "占い師", "C": "村人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "狂人", "I": "狩人", "J": "霊能者", DUMMY: "村人"}
        picked: list = []
        play(prep, roles, POSTERIOR, "grey", FirstRng(), [], cat="off", observer=lambda day, pb, ws, wp, target: picked.append((day, target, wp[target])))
        self.assertEqual(picked[0][:2], (1, "A"))                                        # 黒を出した A は偽(人狼の見込み9割)。黒先の C ではない
        self.assertGreater(picked[0][2], 0.85)

    def test_without_any_world_it_falls_back_to_the_grey_pick(self):
        board = make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        prep = prepare(board)
        roles, _ = sample_world(prep, random.Random(3))
        trace: list = []
        with mock.patch("zinro_learn.progress.enumerate_worlds", return_value=[]):
            play(prep, roles, POSTERIOR, "grey", random.Random(1), trace, cat="off")
        self.assertTrue(any(t[0] == "hang" for t in trace))
        self.assertFalse(any(t[0] == "pick" for t in trace))

    def test_the_public_board_carries_the_later_black_habit_of_the_simulation(self):
        """夜の結果は、シミュレーションの偽の占いが黒を出す重み(FAKE_BLACK_LATER)で、盤面の世界の重みに入る(依頼者: 偽の二手目は、だいたい白)。"""
        board = make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        prep = prepare(board)
        roles, _ = sample_world(prep, random.Random(3))
        seen: list = []
        play(prep, roles, POSTERIOR, "grey", random.Random(1), cat="off", observer=lambda day, pb, ws, wp, target: seen.append(pb.fake_black_later))
        self.assertTrue(seen and set(seen) == {FAKE_BLACK_LATER})
        seen.clear()
        with mock.patch("zinro_learn.progress.FAKE_BLACK_LATER", 0.3):
            play(prep, roles, POSTERIOR, "grey", random.Random(1), cat="off", observer=lambda day, pb, ws, wp, target: seen.append(pb.fake_black_later))
        self.assertTrue(seen and set(seen) == {0.3})

    def test_the_observer_sees_the_deaths_and_reports_pile_up(self):
        board = make_board("10a-kari", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        prep = prepare(board)
        roles = {"A": "占い師", "B": "人狼", "C": "村人", "D": "村人", "E": "人狼", "F": "村人", "G": "狩人", "H": "狂人", "I": "霊能者", DUMMY: "村人"}
        boards: dict[int, object] = {}
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", observer=lambda day, pb, ws, wp, target: boards.setdefault(day, pb))
        self.assertEqual(boards[1].executed, [])
        hung = [t[1] for t in trace if t[0] == "hang"]
        bitten = [t[1] for t in trace if t[0] == "bite"]
        self.assertEqual(boards[2].executed, hung[:1])
        self.assertEqual(boards[2].bitten, bitten[:1])
        self.assertIn({"kind": "霊能", "player": "I", "target": hung[0], "color": "白" if roles[hung[0]] != "人狼" else "黒", "first": False}, boards[2].results)

    def test_the_policy_is_named_and_listed_after_the_fixed_ones(self):
        self.assertEqual(ALL_POLICIES, (*POLICIES, POSTERIOR))
        self.assertEqual(POLICY_NAME[POSTERIOR], "尤度吊り")
        board = make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        prep = prepare(board)
        roles, _ = sample_world(prep, random.Random(1))
        with self.assertRaises(ValueError):
            play(prep, roles, "???", "grey", random.Random(1), cat="off")

    def test_comparing_policies_gives_the_same_numbers_serially_and_in_parallel(self):
        board = make_board("10a-kari", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])
        serial = compare_policies(board, ALL_POLICIES, "grey", n=48, seed=2, workers=1, guard="env", cat="off", hunter="gidra")
        parallel = compare_policies(board, ALL_POLICIES, "grey", n=48, seed=2, workers=2, guard="env", cat="off", hunter="gidra")
        self.assertEqual(serial, parallel)
        self.assertEqual(set(serial), set(ALL_POLICIES))
        self.assertEqual(serial, compare_policies(board, ALL_POLICIES, "grey", n=48, seed=2, workers=1, guard="env", cat="off", hunter="gidra"))

    def test_reading_the_board_every_day_beats_every_fixed_progression_on_three_one(self):
        board = make_board("11a", 3, [dict(player="A", target="D", color="白"), dict(player="B", target="E", color="白"), dict(player="C", target="F", color="白")])
        r = compare_policies(board, ALL_POLICIES, "grey", n=700, seed=4, workers=2, guard="env", cat="off", hunter="gidra")
        self.assertGreater(r[POSTERIOR], max(r[p] for p in POLICIES) + 0.03)           # 3-1 白白白: 読みながら吊る方が、固定の進行より上(目安は +10 点)


class SeersFirstTest(unittest.TestCase):
    """進行提示: 先黒吊り(黒を出された人を先に吊る)と、占い吊り優先(占いの名乗りを先に吊り、黒先は占いのあと)。"""

    def _board(self, target: str):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("C", "占い師"), ("K", "霊能者")]
        board.results = [dict(kind="占い", first=True, player="A", target=target, color="黒")]
        prep = prepare(board)
        prep.wolf_prob.update({"A": 0.0, "B": 0.9, "C": 0.8})          # 村は A を本物と見て、B・C の順に吊る
        roles = {"A": "占い師", "B": "人狼", "C": "狂人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "人狼", "I": "狩人", "J": "猫又", "K": "霊能者"}
        return prep, roles

    def test_black_first_hangs_the_black_target_and_seers_first_hangs_the_seers_before_it(self):
        prep, roles = self._board("F")                                  # 狼の噛みは、灰の先頭から(D、E)なので、F は残る
        trace: list = []
        play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False)
        self.assertEqual(trace[0], ("hang", "F", "人間"))                   # 先黒吊り: 黒を出された F
        trace = []
        play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, black_first=False)
        self.assertEqual(trace[0], ("hang", "B", "人狼"))                   # 占い吊り優先: 狼の見込みが高い B(本物と見る A は残す)
        hangs = [t[1] for t in trace if t[0] == "hang"]
        self.assertEqual(hangs[:3], ["B", "C", "F"])                        # 占いを吊り終えたら、黒先 F

    def test_the_grey_progression_has_no_seer_to_hang_so_black_first_comes_back_at_once(self):
        prep, roles = self._board("F")
        a: list = []
        b: list = []
        play(prep, roles, "grey", "grey", FirstRng(), a, seer_results=False)
        play(prep, roles, "grey", "grey", FirstRng(), b, seer_results=False, black_first=False)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[0], ("hang", "F", "人間"))

    def test_a_black_given_cat_may_stay_hidden_when_the_seers_are_hanged_first_and_comes_out_only_when_it_is_her_turn(self):
        prep, roles = self._board("J")                                  # 黒を刺された J が真猫
        with mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 0.0), mock.patch("zinro_learn.progress.CAT_HIDE_SEERS_FIRST", 1.0):
            trace: list = []
            play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, cat="gidra", black_first=False)
        self.assertEqual(trace[0], ("hang", "B", "人狼"))                   # 伏せていて、占いが吊られる
        names = [t[:2] for t in trace]
        self.assertNotIn(("cat", "J"), names[:6])
        self.assertLess(names.index(("hang", "C")), names.index(("cat", "J")))             # 占いを吊り終えて、黒先として吊られる番に、名乗る
        self.assertLess(names.index(("cat", "J")), names.index(("hang", "J")))
        self.assertEqual(trace[names.index(("cat", "J"))], ("cat", "J", "黒"))
        with mock.patch("zinro_learn.progress.FAKE_CAT_PROACTIVE", 0.0), mock.patch("zinro_learn.progress.CAT_HIDE_SEERS_FIRST", 0.0):
            trace = []
            play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, cat="gidra", black_first=False)
        self.assertEqual(trace[0], ("cat", "J", "黒"))                      # 伏せなければ、朝のうちに名乗る
        self.assertEqual(trace[1][0], "fakecat")                            # 人狼側は確定させたくないので、対抗猫が出る
        self.assertLess(CAT_HIDE_SEERS_FIRST, 1.0)

    def test_seers_first_does_not_change_the_result_when_the_black_is_on_a_seer(self):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("C", "占い師"), ("K", "霊能者")]
        board.results = [dict(kind="占い", first=True, player="A", target="B", color="黒")]
        first = win_rate(board, "roll_keep", "grey", n=6000, seed=3, cat="gidra", guard="env")["rate"]
        second = win_rate(board, "roll_keep", "grey", n=6000, seed=3, cat="gidra", guard="env", black_first=False)["rate"]
        self.assertAlmostEqual(first, second, delta=0.03)                   # B は占いの名乗りで、狼の見込みが高く、どちらでも先に吊られる


class ReadsTest(unittest.TestCase):
    """村の読み: 霊能の報告と食い違う結果を出した占いは偽と分かる(結果は信じず、先に吊る)。黒を当てた占いは、本物と見る。"""

    def _board(self, black_by: str, target: str):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
        board.claims = [("A", "占い師"), ("B", "占い師"), ("C", "占い師"), ("K", "霊能者")]
        board.results = [dict(kind="占い", first=True, player=black_by, target=target, color="黒")]
        prep = prepare(board)
        prep.wolf_prob.update({"A": 0.0, "B": 0.9, "C": 0.8})          # 村は A を本物と見る
        return prep

    def test_a_seer_whose_black_target_is_reported_white_is_found_fake_and_hanged_next(self):
        prep = self._board("A", "F")
        roles = {"A": "人狼", "B": "占い師", "C": "狂人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "人狼", "I": "狩人", "J": "猫又", "K": "霊能者"}
        trace: list = []
        play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False)
        names = [t[:2] for t in trace]
        self.assertEqual(names[0], ("hang", "F"))                           # 黒先 F(実は村人)
        self.assertIn(("report", "F", "白"), trace)
        self.assertIn(("refuted", "A", "F黒"), trace)                       # 黒を出した A は偽と分かる
        self.assertLess(names.index(("report", "F")), names.index(("hang", "A")))
        self.assertLess(names.index(("hang", "A")), names.index(("hang", "B")))        # B・C より先に、偽と分かった A を吊る
        trace = []
        play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, reads=False)
        self.assertEqual([t[1] for t in trace if t[0] == "hang"][:2], ["F", "B"])      # 読まなければ、A を信じつづけて、B を吊る
        self.assertNotIn("refuted", [t[0] for t in trace])

    def test_a_seer_who_hit_a_black_is_trusted_and_the_other_is_hanged(self):
        prep = self._board("B", "F")
        roles = {"A": "人狼", "B": "占い師", "C": "狂人", "D": "村人", "E": "村人", "F": "人狼", "G": "人狼", "H": "村人", "I": "狩人", "J": "猫又", "K": "霊能者"}
        trace: list = []
        play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False)
        hangs = [t[1] for t in trace if t[0] == "hang"]
        self.assertEqual(hangs[0], "F")                                     # 黒先 F は人狼(霊能の報告も黒)
        self.assertIn(hangs[1], ("C", "A"))                                 # 黒を当てた B を残して、それまで本物と見ていた A も、C も吊る
        self.assertNotIn("B", hangs[:3])
        trace = []
        play(prep, roles, "roll_keep", "grey", FirstRng(), trace, seer_results=False, reads=False)
        self.assertEqual([t[1] for t in trace if t[0] == "hang"][:2], ["F", "B"])      # 読まなければ、本物の B を吊る

    def test_without_the_medium_nothing_is_learned(self):
        board = Board(players=list("ABCDEFGHIJK"), roles=dict(ROLES_12A_NEKO), rco=True)
        board.claims = [("B", "占い師"), ("C", "占い師"), ("D", "占い師"), ("A", "霊能者")]
        board.results = [dict(kind="占い", first=True, player="B", target="G", color="黒")]
        prep = prepare(board)
        prep.wolf_prob.update({"B": 0.0, "C": 0.9, "D": 0.8})
        roles = {"A": "霊能者", "B": "人狼", "C": "占い師", "D": "狂人", "E": "村人", "F": "村人", "G": "村人", "H": "人狼", "I": "狩人", "J": "猫又", "K": "人狼"}
        trace: list = []
        play(prep, roles, "roll_keep", "claim", FirstRng(), trace, seer_results=False)          # 名乗りを噛む: 霊能 A が噛まれて、報告が出ない
        self.assertEqual([t[:2] for t in trace[:2]], [("hang", "G"), ("bite", "A")])
        self.assertNotIn("refuted", [t[0] for t in trace])
        self.assertEqual([t[1] for t in trace if t[0] == "hang"][:2], ["G", "C"])             # B を信じつづけて、C を吊る


class RppTest(unittest.TestCase):
    """同数のときの票(依頼者の説明): 人外側(人狼と狂人)が村と同数なら、同数で抽選(RPP)。上回れば通る(PP)。"""

    def _eight(self):
        board = Board(players=list("ABCDEFGH"), roles={"人狼": 3, "狂人": 1, "村人": 4})
        roles = {"A": "人狼", "B": "人狼", "C": "人狼", "D": "狂人", "E": "村人", "F": "村人", "G": "村人", "H": "村人"}
        return prepare(board), roles

    def test_four_to_four_is_a_lottery_between_the_wolf_sides_pick_and_the_villages_pick(self):
        prep, roles = self._eight()
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False)                       # 抽選で人外側の選んだ村人が吊られる
        self.assertEqual(trace[:2], [("rpp", "E", "A"), ("hang", "E", "人間")])
        self.assertFalse(play(prep, roles, "grey", "grey", FirstRng(), [], seer_results=False))        # 村人が吊られれば、夜に人狼3・人間3で負け
        trace = []
        play(prep, roles, "grey", "grey", LateRng(), trace, seer_results=False)                        # 抽選で村の選んだ人外側が吊られる
        self.assertEqual(trace[:2], [("rpp", "E", "A"), ("hang", "A", "人狼")])

    def test_the_wolf_side_wins_the_vote_outright_when_it_outnumbers_the_village(self):
        board = Board(players=list("ABCDEFG"), roles={"人狼": 3, "狂人": 1, "村人": 3})
        prep = prepare(board)
        roles = {"A": "人狼", "B": "人狼", "C": "人狼", "D": "狂人", "E": "村人", "F": "村人", "G": "村人"}
        trace: list = []
        self.assertFalse(play(prep, roles, "grey", "grey", LateRng(), trace, seer_results=False))     # 抽選でなく、必ず通る
        self.assertEqual(trace, [("pp", "E", ""), ("hang", "E", "人間")])

    def test_the_village_votes_for_the_believed_black_when_it_is_in_the_wolf_side(self):
        board = Board(players=list("ABCDEFGH"), roles={"人狼": 3, "狂人": 1, "占い師": 1, "村人": 3}, rco=True)
        board.claims = [("A", "占い師")]
        board.results = [dict(kind="占い", first=True, player="A", target="D", color="黒")]
        prep = prepare(board)
        roles = {"A": "占い師", "B": "人狼", "C": "人狼", "D": "人狼", "E": "狂人", "F": "村人", "G": "村人", "H": "村人"}
        trace: list = []
        play(prep, roles, "grey", "grey", LateRng(), trace, seer_results=False)
        self.assertEqual(trace[:2], [("rpp", "A", "D"), ("hang", "D", "人狼")])      # 先頭の B でなく、黒と信じる D にまとまる(抽選で当たれば吊られる)

    def test_rpp_off_leaves_the_vote_to_the_village(self):
        prep, roles = self._eight()
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, rpp=False)
        self.assertEqual(trace[0], ("hang", "A", "人狼"))

    def test_without_the_madman_nothing_changes(self):
        four = Board(players=list("ABCD"), roles={"人狼": 1, "村人": 3})
        self.assertEqual(win_rate(four, "grey", "grey", n=3000, seed=3)["rate"], win_rate(four, "grey", "grey", n=3000, seed=3, rpp=False)["rate"])

    def test_a_known_wolf_is_not_enough_at_four_to_four(self):
        """村が人狼を1人確定させていても、4:4 では抽選になる。確定がなければ、そもそも勝ち目が薄い(約 3%)。"""
        board = Board(players=list("ABCDEFGH"), roles={"人狼": 3, "狂人": 1, "占い師": 1, "村人": 3}, rco=True)
        board.claims = [("A", "占い師")]
        board.results = [dict(kind="占い", first=True, player="A", target="B", color="黒")]
        prep = prepare(board)
        roles = {"A": "占い師", "B": "人狼", "C": "人狼", "D": "人狼", "E": "狂人", "F": "村人", "G": "村人", "H": "村人"}
        with_rpp = sum(play(prep, roles, "grey", "grey", random.Random(i), seer_results=False) for i in range(3000)) / 3000
        without = sum(play(prep, roles, "grey", "grey", random.Random(i), seer_results=False, rpp=False) for i in range(3000)) / 3000
        self.assertGreater(without, 0.1)
        self.assertLess(with_rpp, without - 0.05)                           # 確定した黒先でも、抽選で半分は村人が吊られる

    def test_the_conditional_win_rate_counts_only_matching_worlds(self):
        board = neko("ABC", [{"player": "A", "target": "E", "color": "黒"}])
        result = win_rate(board, "roll_keep", "grey", n=300, seed=2, where=lambda roles: roles["E"] == "猫又")
        self.assertEqual(result["n"], 300)
        self.assertEqual(result["by_label"].keys() <= {"真狼狼", "真狼狂", "真狂狼"}, True)
        with self.assertRaises(ValueError):
            win_rate(board, "roll_keep", "grey", n=5, seed=2, where=lambda roles: False)


class ComparisonTest(unittest.TestCase):
    def test_the_first_hang_hits_a_seer_more_than_a_grey_in_3_1(self):
        """昼1の1本目: 3-1 では、占いの名乗り1人が人狼の見込み 5/12、灰1人が 1/4(真狂狼 7.5 : 真狼狼 2.5 の重み)。霊能は本物。"""
        rates = hit_rates(neko("ABC"))
        for p in "ABC":
            self.assertAlmostEqual(rates["占い"][p], 5 / 12, places=6)
        self.assertAlmostEqual(rates["灰"], 0.25, places=6)
        self.assertEqual(rates["灰の人数"], 7)
        self.assertEqual(rates["霊能"], 0.0)
        two = hit_rates(neko("AB"))
        self.assertGreater(two["占い"]["A"], two["灰"])

    def test_a_counter_black_makes_the_receiver_the_likely_wolf(self):
        rates = hit_rates(neko("ABC", [{"player": "A", "target": "B", "color": "黒"}]))["占い"]
        self.assertGreater(rates["B"], 0.7)
        self.assertLess(rates["A"], 0.25)

    def test_the_seer_roller_beats_grey_when_the_wolves_sit_among_the_seers(self):
        board = neko("ABC")
        with mock.patch("zinro_learn.progress.LEAVE_CLAIMANT", 0.0):                      # 名乗りを残す噛み方は別に見る(LeaveClaimantTest)
            table = compare(board, n=6000, seed=4, cat="off")               # 猫又の道連れは、別に確かめる
        grey, keep, stop = (table[("grey", p)]["rate"] for p in ("grey", "roll_keep", "roll_stop"))
        self.assertGreater(keep, grey + 0.05)
        self.assertGreater(stop, grey + 0.1)
        # 狼が名乗りを噛むと、灰だけ吊る進行は、名乗りの中の狼を吊れず、まず勝てない
        self.assertLess(table[("claim", "grey")]["rate"], 0.02)
        self.assertGreater(table[("claim", "roll_keep")]["rate"], 0.1)

    def test_the_guard_choice_changes_the_win_rate_and_the_report_names_everything(self):
        board = neko("ABC", [{"player": "A", "target": "B", "color": "黒"}])
        plain = compare(board, n=4000, seed=4, bites=("claim",))[("claim", "roll_keep")]["rate"]
        guarded = compare(board, n=4000, seed=4, bites=("claim",), guard="blacksayer")[("claim", "roll_keep")]["rate"]
        self.assertGreater(guarded, plain)
        text = compare_text(board, "3-1 対抗黒", n=500, seed=1)
        for word in ("占いロラ", "黒スト", "ロラ完遂", "グレー", "灰を噛む", "名乗りを噛む", "構成の割合"):
            self.assertIn(word, text)
        self.assertEqual(set(GUARDS), {None, "medium", "blacksayer", "env", "either"})
        self.assertEqual(set(BITES), {"grey", "claim"})


if __name__ == "__main__":
    unittest.main()
