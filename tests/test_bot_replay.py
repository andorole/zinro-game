import unittest

from zinro_bot.replay import burst_starts, rename, spread, table_from_game, truth_burst

NAMES = {"A": "アキラ", "B": "ブン", "C": "シン"}


def speech(seq, speaker, text):
    return {"seq": seq, "kind": "speech", "speaker": speaker, "text": text, "phase": "day"}


GAME = {
    "game_id": "g",
    "players": {"A": {"role": "村人"}, "B": {"role": "人狼"}, "C": {"role": "村人"}},
    "events": [
        {"seq": 1, "kind": "system", "text": "恐ろしい夜が明け、朝になりました。", "phase": "day"},
        speech(2, "A", "おはよう"),
        speech(3, "B", "おは"),
        {"seq": 4, "kind": "spirit", "speaker": "O1", "text": "見てる", "phase": "day"},
        speech(5, "B", "《A》さんはどう思う？"),
        speech(6, "C", "どう思う、は？"),
        speech(7, "B", "根拠は"),
        speech(8, "B", "それだけ？"),
        speech(9, "A", "うん"),
    ],
}


class ReplayTest(unittest.TestCase):
    def test_rename_replaces_only_labels(self):
        self.assertEqual(rename("《A》さんと4Aの話", NAMES), "アキラさんと4Aの話")

    def test_burst_starts_and_truth(self):
        self.assertEqual(burst_starts(GAME, "B"), [3, 7])
        self.assertEqual([t["text"] for t in truth_burst(GAME, 3, "B", NAMES)], ["おは", "アキラさんはどう思う？"])
        self.assertEqual([t["game_seq"] for t in truth_burst(GAME, 7, "B", NAMES)], [7, 8])

    def test_table_from_game_numbers_posts_and_hides_spirit(self):
        table, seqmap = table_from_game(GAME, 7, "B", NAMES)
        self.assertEqual([(p.seq, p.speaker) for p in table.posts], [(1, "アキラ"), (2, "ブン"), (3, "ブン"), (4, "シン")])
        self.assertEqual((table.me, table.role, table.phase), ("ブン", "人狼", "day"))
        self.assertEqual(seqmap, {2: 1, 3: 2, 5: 3, 6: 4})
        self.assertEqual(table.posts[2].text, "アキラさんはどう思う？")

    def test_spread(self):
        self.assertEqual(spread([1, 2, 3, 4, 5, 6, 7], 3), [1, 4, 7])
        self.assertEqual(spread([1, 2], 5), [1, 2])


if __name__ == "__main__":
    unittest.main()
