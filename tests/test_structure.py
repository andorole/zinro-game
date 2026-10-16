import unittest

from zinro_learn.structure import format_structure, group_of, reply_kind, reply_summary, run_lengths, run_summary

# 形の確認用に作った架空のゲーム(実在のログではない)。A・B はベース・次点の話者。
SPEAKERS = ["C", "A", "A", "B", "C", "B", "B", "B", "A", "C"]
GAME = {
    "game_id": "g",
    "players": {},
    "events": [
        *(
            {"seq": i, "kind": "speech", "speaker": who, "phase": "day", "text": "x"}
            for i, who in enumerate(SPEAKERS, 1)
        ),
        {"seq": 11, "kind": "system", "phase": "vote", "text": "x"},
    ],
}


def ex(number, seq, speaker, reply_to, tier=None):
    return {"id": f"ex{number}", "game": "g", "seq": seq, "speaker": speaker, "reply_to": reply_to,
            "tier": tier or {"B": 1, "A": 2}.get(speaker, 3)}


class RunTest(unittest.TestCase):
    def test_run_lengths_count_consecutive_posts_of_one_speaker(self):
        self.assertEqual(
            run_lengths(GAME),
            [("C", 1, 1), ("A", 2, 2), ("B", 1, 4), ("C", 1, 5), ("B", 3, 6), ("A", 1, 9), ("C", 1, 10)],
        )

    def test_run_summary_by_group(self):
        summary = run_summary([GAME])
        self.assertEqual(summary["B"]["posts"], 4)
        self.assertEqual(summary["B"]["in_runs"], 3)  # 3連投の3件
        self.assertEqual(summary["B"]["longest"], 3)
        self.assertEqual(summary["A"]["runs"][2], 1)
        self.assertEqual(summary["他"]["in_runs"], 0)
        self.assertEqual(group_of("D"), "他")


class ReplyKindTest(unittest.TestCase):
    def setUp(self):
        self.speech = [e for e in GAME["events"] if e["kind"] == "speech"]

    def kind(self, seq, speaker, reply_to):
        return reply_kind(ex(1, seq, speaker, reply_to), self.speech)

    def test_kinds(self):
        self.assertEqual(self.kind(1, "C", []), ("opener", []))
        self.assertEqual(self.kind(3, "A", [2]), ("continue", []))  # 自分の直前の続き
        self.assertEqual(self.kind(4, "B", [3]), ("direct", [1]))  # 直前の他人の発言
        self.assertEqual(self.kind(5, "C", [3]), ("skip", [2]))  # 直前の他人(B・seq 4)を飛ばす
        self.assertEqual(self.kind(5, "C", [3, 4]), ("multi", [2, 1]))
        self.assertEqual(self.kind(7, "B", [5, 6]), ("direct", [2]))  # 自分の発言は数えない

    def test_summary_and_report(self):
        examples = [ex(1, 4, "B", [3]), ex(2, 5, "C", [3]), ex(3, 5, "C", [3, 4], tier=3), ex(4, 3, "A", [2])]
        summary = reply_summary(examples, {"g": GAME})
        self.assertEqual(dict(summary["B"]["kinds"]), {"direct": 1})
        self.assertEqual(dict(summary["他"]["kinds"]), {"skip": 1, "multi": 1})
        self.assertEqual(summary["他"]["skip_distances"], [2])
        self.assertEqual(dict(summary["A"]["kinds"]), {"continue": 1})
        report = format_structure({"g": GAME}, examples)
        self.assertIn("連投", report)
        self.assertIn("返信の型", report)


if __name__ == "__main__":
    unittest.main()
