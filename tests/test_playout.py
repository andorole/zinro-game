import contextlib
import io
import unittest

from zinro_learn.__main__ import main
from zinro_learn.board import DUMMY, make_board
from zinro_learn.playout import playout_text, wolf_line


def board():
    return make_board("11a", 2, [dict(player="A", target="C", color="白"), dict(player="B", target="D", color="白")])


class PlayoutTest(unittest.TestCase):
    """1試合を動かして、朝ごとの盤面(昼1・昼2・昼3…)を並べる(依頼者: 昼2・昼3・昼4の盤面も計算で導く)。"""

    def test_it_lists_the_boards_of_the_first_days_the_hang_and_the_result(self):
        text = playout_text(board(), bite="grey", seed=4, guard="env", cat="off", hunter="gidra")      # 灰を噛む: 霊能が生き残り、報告が出る
        for needle in ("== 昼1の盤面(生存 10 人", "== 昼2の盤面", "人狼の見込み(高い順):", "吊り先(尤度吊り):", "吊り: ", "夜の襲撃: ", "霊能の報告: ", "== 結果: ", "正体: "):
            self.assertIn(needle, text)
        self.assertLess(text.index("昼1の盤面"), text.index("昼2の盤面"))
        self.assertIn(f"{DUMMY}=", text)                                      # ダミーの役職(欠けた役職)も、最後に明かす

    def test_the_same_seed_gives_the_same_game_and_another_seed_another(self):
        a = playout_text(board(), seed=2, cat="off")
        self.assertEqual(a, playout_text(board(), seed=2, cat="off"))
        self.assertNotEqual(a, playout_text(board(), seed=3, cat="off"))

    def test_a_fixed_progression_can_be_shown_too_and_the_roles_can_be_given(self):
        roles = {"A": "人狼", "B": "占い師", "C": "村人", "D": "村人", "E": "村人", "F": "村人", "G": "人狼", "H": "狂人", "I": "狩人", "J": "霊能者", DUMMY: "村人"}
        text = playout_text(board(), policy="roll_keep", roles=roles, cat="off")
        self.assertIn("吊り先(占いロラ):", text)
        self.assertIn("A=人狼 B=占い師", text)
        self.assertIn("吊り: ", text)
        self.assertIn("高い方から ", text)                                      # 固定の進行でも、吊り先が人狼の見込みで何番目かを示す(占いロラは、見込みと関係なく吊るので、低い順位のこともある)

    def test_the_claims_made_for_the_days_hang_come_after_the_board_and_before_the_target(self):
        """黒を刺された猫又の名乗りや、対抗の猫は、その日の盤面と見込みのあと、吊り先の前に出る(前の夜のできごとは、盤面の前)。"""
        b = make_board("12a-neko", 3, [dict(player="A", target="D", color="黒")])
        roles = {"A": "人狼", "B": "占い師", "C": "狂人", "D": "猫又", "E": "村人", "F": "村人", "G": "人狼", "H": "村人", "I": "狩人", "J": "人狼", "K": "霊能者", DUMMY: "村人"}
        text = playout_text(b, seed=1, roles=roles, cat="gidra", hunter="gidra")
        lines = text.splitlines()
        first = lines.index(next(line for line in lines if line.startswith("== 昼1の盤面")))
        wolf = next(i for i, line in enumerate(lines) if line.startswith("人狼の見込み(高い順):") and i > first)
        target = next(i for i, line in enumerate(lines) if line.startswith("吊り先(") and i > first)
        claims = [i for i, line in enumerate(lines) if "猫又CO" in line]
        self.assertTrue(claims, text)
        self.assertTrue(all(wolf < i < target for i in claims[:1]), (wolf, claims, target))
        second = next(i for i, line in enumerate(lines) if line.startswith("== 昼2の盤面"))
        self.assertTrue(any(line.startswith("  吊り: ") for line in lines[target:second]))         # 吊りは、吊り先のあと

    def test_the_wolf_line_ranks_the_living_by_the_chance_of_being_a_wolf(self):
        b = board()
        line = wolf_line(b, {"A": 0.5, "B": 0.5, "C": 0.1})
        self.assertTrue(line.startswith("人狼の見込み(高い順): A 50%、B 50%、"))
        self.assertIn("C 10%", line)
        self.assertNotIn(DUMMY, line)                                          # 最初から死んでいるダミーは、並べない

    def test_the_command_line_plays_one_game(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["playout", "--setup", "10a-kari", "--seers", "2", "--result", "A:C:白", "--result", "B:D:白", "--seed", "3", "--policy", "grey", "--hunter", "gidra"])
        text = out.getvalue()
        self.assertIn("昼1の盤面(生存 9 人", text)
        self.assertIn("吊り先(グレー)", text)
        self.assertIn("== 結果: ", text)


if __name__ == "__main__":
    unittest.main()
