import json
import tempfile
import unittest
from pathlib import Path

from zinro_learn.check import PLACEHOLDER, check, longest_overlap, sync_table

TABLE = """\
| 型 | いつ使うか | 形のめやす | 主な話者 | 例 |
|---|---|---|---|---|
| rebut | 反論する | 否定 → 理由 | B9 | ex99 |
"""


def example(number, speaker, role, moves, utterance, seq, reply_to=()):
    return {
        "id": f"ex{number:02d}", "game": "g1", "seq": seq, "speaker": speaker, "role": role,
        "tier": {"B": 1, "A": 2}.get(speaker, 3), "register": "タメ口", "phase": "day",
        "reply_to": list(reply_to), "moves": moves, "situation": "場面", "utterance": utterance,
    }


EXAMPLES = [
    example(1, "B", "村人", ["rebut"], "それは違うと思う。", 2, [1]),
    example(2, "A", "人狼", ["rebut", "probe"], "本当に、そう言い切れますか？", 3, [2]),
    example(3, "C", "村人", ["probe"], "どうして？", 4, [2, 3]),
]
GAME = {
    "game_id": "g1",
    "players": {"A": {"role": "人狼"}, "B": {"role": "村人"}, "C": {"role": "村人"}},
    "events": [
        {"seq": 1, "kind": "speech", "speaker": "C", "phase": "day", "text": "x"},
        *(
            {"seq": seq, "kind": "speech", "speaker": speaker, "phase": "day", "text": "x"}
            for seq, speaker in ((2, "B"), (3, "A"), (4, "C"))
        ),
        {"seq": 5, "kind": "system", "phase": "day", "text": "x"},
    ],
}


def write_project(root: Path, examples=EXAMPLES, table=TABLE, game=GAME) -> None:
    (root / "knowledge").mkdir(parents=True)
    rows = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in examples)
    (root / "knowledge/examples.jsonl").write_text(rows, encoding="utf-8")
    (root / "knowledge/discussion_style.md").write_text(table, encoding="utf-8")
    (root / "logs/normalized").mkdir(parents=True)
    (root / "logs/normalized/g1.json").write_text(json.dumps(game, ensure_ascii=False), encoding="utf-8")


class SyncTest(unittest.TestCase):
    def test_columns_are_rebuilt_and_missing_rows_added(self):
        synced = sync_table(TABLE, EXAMPLES)
        self.assertIn("| rebut | 反論する | 否定 → 理由 | B1 A1 | ex01, ex02 |", synced)
        self.assertIn(f"| probe | {PLACEHOLDER} | {PLACEHOLDER} | A1 他1 | ex02, ex03 |", synced)
        self.assertEqual(sync_table(synced, EXAMPLES), synced)  # 2回目は変わらない


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_placeholder_must_be_filled(self):
        write_project(self.root, table=sync_table(TABLE, EXAMPLES))
        self.assertEqual([p for p in check(self.root) if "未記入" in p], ["型 probe の説明が未記入"])
        filled = sync_table(TABLE, EXAMPLES).replace(PLACEHOLDER, "確認する")
        (self.root / "knowledge/discussion_style.md").write_text(filled, encoding="utf-8")
        self.assertEqual(check(self.root), [])

    def test_stale_table_is_reported(self):
        write_project(self.root)
        problems = check(self.root)
        self.assertTrue(any("rebut の表が発言例とずれている" in p for p in problems))
        self.assertTrue(any("probe が表にない" in p for p in problems))

    def test_example_fields_are_checked_against_the_log(self):
        bad = [
            {**EXAMPLES[0], "tier": 2, "register": "方言", "utterance": "つまり、違う。"},
            {**EXAMPLES[1], "role": "村人"},  # seq 3 の話者 A は人狼
            {**EXAMPLES[2], "seq": 2},  # seq 2 の話者は B
        ]
        write_project(self.root, examples=bad, table=sync_table(TABLE, bad).replace(PLACEHOLDER, "x"))
        problems = " / ".join(check(self.root))
        for expected in ("ex01: tier が 2", "ex01: register", "ex01: 説明口調", "ex02: 役職がログと違う", "ex03: 話者がログと違う"):
            self.assertIn(expected, problems)

    def test_reply_to_is_checked_against_the_log(self):
        late = {**EXAMPLES[2], "id": "ex04", "seq": 6, "speaker": "A", "role": "人狼", "tier": 2, "reply_to": [5]}
        bad = [
            {**EXAMPLES[2], "id": "ex01", "reply_to": [3, 2]},  # 昇順でない
            {**EXAMPLES[1], "id": "ex02", "reply_to": [1, 2, 3, 4, 5]},  # 多すぎる、自分以降もある
            {**EXAMPLES[2], "id": "ex03", "reply_to": "2"},  # リストでない
            late,  # seq 5 はシステム通知
        ]
        game = {**GAME, "events": [*GAME["events"], {"seq": 6, "kind": "speech", "speaker": "A", "phase": "day", "text": "x"}]}
        write_project(self.root, examples=bad, table=sync_table(TABLE, bad).replace(PLACEHOLDER, "x"), game=game)
        problems = " / ".join(check(self.root))
        for expected in ("ex01: reply_to が昇順", "ex02: reply_to が4件を超えて", "ex02: reply_to の seq 3 が自分",
                         "ex03: reply_to が整数のリスト", "ex04: reply_to の seq 5 は発言ではない"):
            self.assertIn(expected, problems)

    def test_reply_to_may_be_empty(self):
        examples = [{**EXAMPLES[0], "reply_to": []}, *EXAMPLES[1:]]
        write_project(self.root, examples=examples, table=sync_table(TABLE, examples).replace(PLACEHOLDER, "x"))
        self.assertEqual(check(self.root), [])

    def test_reply_to_is_required(self):
        missing = {k: v for k, v in EXAMPLES[0].items() if k != "reply_to"}
        write_project(self.root, examples=[missing], table=sync_table(TABLE, [missing]).replace(PLACEHOLDER, "x"))
        self.assertTrue(any("reply_to が整数のリスト" in p for p in check(self.root)))

    def test_real_names_and_long_overlap_are_reported(self):
        long_line = "この一文は原文とそっくり同じで長いです。"
        examples = [{**EXAMPLES[0], "utterance": long_line}, *EXAMPLES[1:]]
        write_project(self.root, examples=examples, table=sync_table(TABLE, examples).replace(PLACEHOLDER, "x"))
        (self.root / "logs/private").mkdir(parents=True)
        (self.root / "logs/private/g1.players.json").write_text(
            json.dumps({"players": {"A": "テスト太郎"}, "aliases": {"太郎": "テスト太郎"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.root / "logs/raw").mkdir(parents=True)
        (self.root / "logs/raw/g1.txt").write_text(f"X: {long_line}\n", encoding="utf-8")
        (self.root / "README.md").write_text("テスト太郎の発言を載せた\n", encoding="utf-8")
        problems = " / ".join(check(self.root))
        self.assertIn("README.md に実名 'テスト太郎'", problems)
        self.assertIn("ex01: 原文と", problems)

    def test_longest_overlap(self):
        self.assertEqual(longest_overlap("あいうえお", "かいうえき"), 3)


if __name__ == "__main__":
    unittest.main()
