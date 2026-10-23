import contextlib
import io
import unittest

from zinro_learn import progress as P
from zinro_learn.__main__ import main
from zinro_learn.board import Board, make_board
from zinro_learn.timing import SCENES, diff, paired, split_result, stderr, timing_text


def neko(seers: int, results=()):
    return make_board("12a-neko", seers, list(results))


class PairedTimingTest(unittest.TestCase):
    """狩人が出るタイミングの比較(対になった比較)。依頼者の問い: 出るタイミングで、どこが有効で、どこがギドラの方が良くて、どこでは指定されない限り潜伏するべきか。"""

    def test_coming_out_without_being_designated_loses_against_waiting_for_the_designation(self):
        for day in (1, 2):
            result = paired(neko(2), "grey", "day", day, 3000, cat="gidra")
            self.assertGreater(result["games"], 1500)                                    # 狩人が生きていて、まだ名乗っていない朝が来る試合
            self.assertLess(diff(result), -0.04)                                         # 自発は損: 出た狩人を狼が噛みに来て、護衛を失う
            self.assertLess(stderr(result), 0.02)

    def test_a_hunter_given_a_black_does_better_by_coming_out_that_morning(self):
        board = neko(3, [dict(player="A", target="D", color="黒")])
        result = paired(board, "grey", "scene", "黒", 4000, cat="gidra")
        self.assertGreater(result["games"], 150)                                         # 黒を出された D が狩人の世界は、1割ほど
        self.assertGreater(diff(result), 0.05)                                           # 黒先で吊られるのを避けられ、黒を出した占いが偽と分かる

    def test_coming_out_after_a_guard_success_loses_the_guard(self):
        saved = P.HUNTER_GJ_CO
        result = paired(neko(2), "grey", "scene", "GJ", 3000, cat="gidra")
        self.assertEqual(P.HUNTER_GJ_CO, saved)                                          # GJ の比較で上書きした割合は、元に戻す
        self.assertGreater(result["games"], 1000)
        self.assertLess(diff(result), -0.03)

    def test_the_same_seed_gives_the_same_numbers_serially_and_in_parallel(self):
        board = neko(2)
        a = paired(board, "roll_stop", "day", 2, 1200, cat="gidra", seed=3, workers=1)
        b = paired(board, "roll_stop", "day", 2, 1200, cat="gidra", seed=3, workers=1)
        c = paired(board, "roll_stop", "day", 2, 1200, cat="gidra", seed=3, workers=2)
        self.assertEqual(a, b)
        self.assertEqual((a["games"], a["alt"], a["base"]), (c["games"], c["alt"], c["base"]))

    def test_the_states_of_the_decision_morning_are_counted_by_alive_and_wolves(self):
        result = paired(neko(2), "grey", "day", 2, 1500, cat="gidra")
        self.assertEqual(sum(row[0] for row in result["rows"].values()), result["games"])
        self.assertTrue(all(alive <= 11 and wolves <= 3 for alive, wolves in result["rows"]))
        alive_counts = {alive for alive, _ in result["rows"]}
        self.assertTrue(alive_counts <= {7, 8, 9, 10})                                   # 昼2の朝: 昼1の吊りと夜の襲撃(と道連れ)のあと

    def test_the_games_are_split_by_whether_the_real_seer_is_missing(self):
        """役欠け(ダミーが本物の占い)の世界では、占いの名乗りは全員偽。「ほかの占いの名乗りが全員偽と分かった=残る占いが本物」という決め打ちが外れる。"""
        result = paired(neko(2), "grey", "day", 1, 3000, cat="gidra")
        split = result["split"]
        self.assertEqual(sum(v[0] for v in split.values()), result["games"])
        self.assertEqual((sum(v[1] for v in split.values()), sum(v[2] for v in split.values())), (result["alt"], result["base"]))
        missing, present = split_result(result, True), split_result(result, False)
        self.assertGreater(missing["games"], 100)                                        # 12A猫は役欠けあり: 11人のうち1枚をダミーが持つ
        self.assertGreater(present["games"], missing["games"] * 3)                       # 占いが欠けている世界は、ありうる(定番より軽い)
        self.assertEqual(missing["games"] + present["games"], result["games"])
        self.assertIsNotNone(diff(missing))
        self.assertIsNotNone(stderr(present))
        plain = Board(players=list("ABCDEFG"), roles={"人狼": 1, "占い師": 1, "霊能者": 1, "狩人": 1, "村人": 3}, rco=True)
        plain.claims = [("A", "占い師"), ("G", "霊能者")]
        only = paired(plain, "grey", "day", 1, 400, cat="off")["split"]
        self.assertEqual(set(only), {False})                                             # ダミーのない盤面では、占いは欠けない

    def test_unknown_modes_and_scenes_are_refused(self):
        with self.assertRaises(ValueError):
            paired(neko(2), "grey", "night", 1, 10)
        with self.assertRaises(ValueError):
            paired(neko(2), "grey", "scene", "夜", 10)
        with self.assertRaises(ValueError):
            paired(neko(2), "grey", "day", 0, 10)
        self.assertEqual(SCENES, ("黒", "詰み", "狩ロラ", "GJ"))

    def test_diff_and_stderr_are_none_without_a_decision_morning(self):
        empty = {"games": 0, "alt": 0, "base": 0, "alt_only": 0, "base_only": 0, "n": 10, "rows": {}}
        self.assertIsNone(diff(empty))
        self.assertIsNone(stderr(empty))

    def test_the_text_lists_every_policy_and_marks_rare_scenes(self):
        text = timing_text(neko(2), "12A猫・2-1", ("grey", "roll"), days=(1, 2), n=600)
        for word in ("12A猫・2-1", "グレー", "ロラ完遂", "自発", "場面", "—"):
            self.assertIn(word, text)

    def test_the_command_line_runs_and_hides_the_hunter_options(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["timing", "--seers", "2", "--n", "300", "--workers", "1", "--days", "1", "2", "--policies", "grey"])
        self.assertIn("グレー", out.getvalue())
        self.assertIn("昼1", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["timing", "--seers", "2", "--hunter", "gidra"])                       # 出る側・出ない側は比較が決めるので、狩人の出方は選べない


if __name__ == "__main__":
    unittest.main()
