import json
import shutil
import tempfile
import unittest
from pathlib import Path

from zinro_bot.llm import ApiError, ScriptedClient
from zinro_bot.replay import burst_starts, last_vote, rename, run_cases, score_case, spread, summarize, table_from_game, truth_burst

ROOT = Path(__file__).resolve().parent.parent

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
        {"seq": 10, "kind": "system", "text": "投票時間になりました。話すのをやめてください。", "phase": "vote"},
        {"seq": 11, "kind": "command", "action": "投票", "actor": "A", "target": "B", "phase": "vote"},
        {"seq": 12, "kind": "command", "action": "投票", "actor": "B", "target": "A", "phase": "vote"},
        {"seq": 13, "kind": "command", "action": "投票", "actor": "C", "target": "B", "phase": "vote"},
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


def reply(text: str, vote=None) -> dict:
    return {
        "read": {"players": {}, "pending": [], "swing": "", "aim": "根拠を聞く"},
        "posts": [{"reply_to": [3], "moves": ["probe"], "text": text}],
        "vote": vote, "silence": "",
    }


class RunCasesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(ROOT / "knowledge", self.root / "knowledge")
        (self.root / "logs/normalized").mkdir(parents=True)
        (self.root / "logs/normalized/g.json").write_text(json.dumps(GAME, ensure_ascii=False), encoding="utf-8")
        self.out = Path(self.tmp.name) / "eval"

    def test_last_vote(self):
        self.assertEqual(last_vote(GAME, "A"), "B")
        self.assertIsNone(last_vote(GAME, "Z"))

    def test_run_cases_writes_outputs_timing_and_summary(self):
        # 1件目の切れ目は最初の発言の前(まだ誰も話していない)なので、票は2件目で出す
        client = ScriptedClient([reply("どこから読んだの？"), reply("その根拠はどこにある？", vote="ブン")])
        cases = run_cases(self.root, "g", "A", 2, self.out, lambda table: client, min_before=0)
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[1]["wolves"], ["ブン"])
        self.assertEqual(cases[1]["actual_vote"], "ブン")
        written = json.loads((self.out / "out" / f"{cases[1]['case']}.json").read_text(encoding="utf-8"))
        self.assertEqual(written["posts"][0]["text"], "その根拠はどこにある？")
        self.assertEqual(written["vote"], "ブン")
        run = json.loads((self.out / "out" / f"{cases[1]['case']}.run.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(run["seconds"], 0)
        self.assertEqual(run["attempts"], 1)
        text = score_case(self.root, self.out, cases[1])
        self.assertIn("票: ボット ブン / 実際 ブン / 狼 ブン", text)
        self.assertIn("所要", text)
        summary = summarize(self.out, cases)
        self.assertIn("ケース 2件", summary)
        self.assertIn("狼を指した: 1件", summary)

    def test_api_failures_are_recorded_and_skipped(self):
        class Broken:
            def complete(self, system, messages):
                raise ApiError("ダメ")

        cases = run_cases(self.root, "g", "A", 1, self.out, lambda table: Broken(), min_before=0)
        self.assertEqual(cases[0]["error"], "ダメ")
        self.assertIn("API の失敗 1件", summarize(self.out, cases))


if __name__ == "__main__":
    unittest.main()
