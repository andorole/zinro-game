import random
import unittest
from unittest import mock

from zinro_learn.board import FAKE_BLACK_FIRST, Board, ROLES_12A_NEKO
from zinro_learn.progress import (
    BITES, ENCLOSE_NEXT, FAKE_BLACK_LATER, GUARDS, POLICIES, compare, compare_text, hit_rates, night_result, play, prepare,
    sample_world, win_rate,
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
        table = compare(board, n=6000, seed=4)
        grey, keep, stop = (table[("grey", p)]["rate"] for p in ("grey", "roll_keep", "roll_stop"))
        self.assertGreater(keep, grey + 0.1)
        self.assertGreater(stop, grey + 0.15)
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
        self.assertEqual(set(GUARDS), {None, "medium", "blacksayer"})
        self.assertEqual(set(BITES), {"grey", "claim"})


if __name__ == "__main__":
    unittest.main()
