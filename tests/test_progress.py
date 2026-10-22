import contextlib
import io
import random
import unittest
from unittest import mock

from zinro_learn.__main__ import main
from zinro_learn.board import FAKE_BLACK_FIRST, Board, ROLES_12A_NEKO, make_board
from zinro_learn.progress import (
    BITES, CAT_HIDE_SEERS_FIRST, CATS, COUNTER_CAT, COUNTER_CAT_BLACK, COUNTER_CAT_WOLF, ENCLOSE_NEXT, FAKE_BLACK_LATER, FAKE_CAT_FIRST, FAKE_CAT_PROACTIVE, FAKE_HUNTER_FIRST,
    GIDRA_CAT, GIDRA_HUNTER, GUARDS, HUNTER_BITE, HUNTER_COUNTER, HUNTER_NAME, HUNTERS, OPEN_CAT_BITE, POLICIES, compare, compare_text, counter_cat, hit_rates, night_result, play,
    prepare, sample_world, win_rate,
)


class FirstRng:
    """いつも先頭を選ぶ乱数(試合を決まった形で動かすための代役)。"""

    def choice(self, seq):
        return seq[0]

    def random(self):
        return 0.0

    def shuffle(self, seq):
        return None


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
        trace: list = []
        play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="fake")     # FirstRng の random() は 0.0: 対抗が出る側
        self.assertEqual(trace[:3], [("fakehunter", "A", "指定"), ("hunter", "E", "対抗"), ("hang", "A", "人狼")])
        self.assertEqual(trace[3][0], "bite")                                            # 出た本物の狩人 E は、噛まれる(HUNTER_BITE)
        self.assertEqual(trace[3][1], "E")

    def test_only_one_hunter_claim_is_made_by_the_wolf_side_on_the_first_day(self):
        prep, roles = self._eleven(A="人狼", B="狂人", H="村人", E="狩人")
        with mock.patch("zinro_learn.progress.HUNTER_COUNTER", 0.0):
            trace: list = []
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="fake")
        self.assertEqual([t[:2] for t in trace[:2]], [("fakehunter", "A"), ("hang", "B")])               # 人狼 A が名乗って避け、次に指定された狂人 B は、重ねて名乗らず、吊られる
        self.assertEqual(len([t for t in trace if t[0] == "fakehunter"]), 1)

    def test_a_fake_hunter_is_only_for_the_first_day(self):
        prep, roles = self._eleven(B="人狼", E="村人", A="村人")
        with mock.patch("zinro_learn.progress.HUNTER_COUNTER", 0.0):
            trace: list = []
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="fake")
        self.assertEqual(trace[0], ("hang", "A", "人間"))                                # 先頭の灰 A は村人: 吊られる
        later = [t for t in trace if t[0] == "fakehunter"]
        self.assertTrue(all(t[1] != "B" for t in later))                                 # 2日目以降に指定された人外は、偽の狩人を名乗らない(入れていない)

    def test_a_real_hunter_who_comes_out_after_a_fake_has_the_earlier_one_hanged(self):
        prep, roles = self._eleven(A="人狼", D="狩人", E="村人")
        with mock.patch("zinro_learn.progress.HUNTER_COUNTER", 0.0), mock.patch("zinro_learn.progress.HUNTER_BITE", 0.0):
            trace: list = []
            play(prep, roles, "grey", "grey", FirstRng(), trace, seer_results=False, cat="off", hunter="fake")
        kinds = [t[:2] for t in trace]
        self.assertEqual(kinds[:3], [("fakehunter", "A"), ("hang", "B"), ("bite", "C")])      # 昼1: 偽の A は吊りを避け、B が吊られる。夜に C が噛まれる
        self.assertIn(("hunter", "D"), kinds)                                            # 昼2: 指定された本物の D が名乗る
        after = kinds[kinds.index(("hunter", "D")) + 1]
        self.assertEqual(after, ("hang", "A"))                                           # 2人の狩人が名乗ったので、先に出た偽の A を吊る

    def test_the_standard_modes_and_the_names(self):
        self.assertEqual(HUNTERS, ("off", "gidra", "fake"))
        self.assertEqual(set(HUNTER_NAME), set(HUNTERS))
        self.assertEqual(GIDRA_HUNTER, 1.0)                                              # 依頼者: 本指定のタイミングで、狩もギドラCOをする
        self.assertTrue(0 < FAKE_HUNTER_FIRST < 1 and 0 < HUNTER_COUNTER < 1 and 0 < HUNTER_BITE < 1)
        prep, roles = self._eleven()
        with self.assertRaises(ValueError):
            play(prep, roles, "grey", "grey", FirstRng(), [], hunter="???")

    def test_the_hunter_gidra_helps_the_village_by_keeping_the_guard_and_the_fake_hunter_saves_the_wolf_side_on_day_one(self):
        board = neko("AB")
        off = win_rate(board, "grey", "claim", n=12000, seed=1, guard="env", cat="gidra")["rate"]
        gidra = win_rate(board, "grey", "claim", n=12000, seed=1, guard="env", cat="gidra", hunter="gidra")["rate"]
        self.assertGreater(gidra, off + 0.04)                                            # 指定された狩人が名乗ると、吊られずに護衛が残る分、村が得をする
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
        table = compare(board, n=6000, seed=4, cat="off")                   # 猫又の道連れは、別に確かめる
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
        self.assertEqual(set(GUARDS), {None, "medium", "blacksayer", "env"})
        self.assertEqual(set(BITES), {"grey", "claim"})


if __name__ == "__main__":
    unittest.main()
