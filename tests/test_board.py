import json
import unittest
from collections import Counter
from itertools import permutations
from pathlib import Path

from zinro_learn.board import (
    Board, board_at, claim_patterns, confirmed, enumerate_worlds, load_record, narrowing_wins, next_hang_line,
    marginals, pattern_label, patterns_text, rope_slack, stage_report, world_judgement,
)

ROOT = Path(__file__).resolve().parent.parent
SMALL = {"人狼": 1, "狂人": 1, "占い師": 1, "霊能者": 1, "村人": 2}


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
        self.assertNotIn("真狼-狼", by_tier[3] + by_tier[2])         # 霊の偽は、まれ
        self.assertIn("真狼-狼", by_tier[1])
        self.assertIn("2-1: 定番: 真狼-真 | ありうる: 真狂-真 | まれ:", patterns_text())

    def test_a_lone_medium_is_real_in_the_standard_case(self):
        rows = claim_patterns(0, 1)
        self.assertEqual(sorted({r["label"] for r in rows if r["tier"] == 3}), ["なし-真"])
        self.assertEqual({r["label"] for r in rows if r["tier"] == 1}, {"なし-狼", "なし-狂"})

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


if __name__ == "__main__":
    unittest.main()
