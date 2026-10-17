import unittest
from pathlib import Path

from zinro_bot.prompt import as_text, build_system, moves_text, read_section, select_examples, vocabulary_text
from zinro_learn.check import load_examples

ROOT = Path(__file__).resolve().parent.parent


class PromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = load_examples(ROOT / "knowledge/examples.jsonl")
        cls.style = (ROOT / "knowledge/discussion_style.md").read_text(encoding="utf-8")

    def test_read_section_stops_at_next_heading(self):
        text = "# 題\n## 甲\nあ\n## 乙\nい\n"
        self.assertEqual(read_section(text, "甲").strip(), "あ")
        self.assertEqual(read_section(text, "乙").strip(), "い")
        self.assertEqual(read_section(text, "丙"), "")

    def test_moves_and_vocabulary_lists(self):
        moves = moves_text(self.style)
        self.assertIn("- rebut: ", moves)
        self.assertIn("- turnabout: ", moves)
        vocabulary = vocabulary_text(self.style)
        self.assertIn("- 起点: ", vocabulary)
        self.assertNotIn("---", vocabulary)

    def test_system_blocks_are_cached_and_filled(self):
        blocks = build_system(ROOT, me="ボブ", role="人狼", register="敬語")
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(b["cache_control"] == {"type": "ephemeral"} for b in blocks))
        text = as_text(blocks)
        self.assertIn("プレイヤー「ボブ」。役職は人狼", text)
        self.assertIn("語調は敬語で通す", text)
        self.assertNotIn("{me}", text)
        self.assertIn("【rebut】", text)
        self.assertIn("【避ける動き", text)

    def test_unset_name_and_role_get_placeholders(self):
        text = as_text(build_system(ROOT))
        self.assertIn("（あなたの名前）", text)
        self.assertNotIn("{role}", text)

    def test_excluded_games_and_avoid_examples_are_not_selected(self):
        selected = select_examples(self.examples, "村人", exclude_games=("log08", "log11"))
        chosen = [e for rows in selected["own"].values() for e in rows] + selected["opponent"] + selected["avoid"]
        self.assertTrue(chosen)
        self.assertFalse([e for e in chosen if e["game"] in ("log08", "log11")])
        positive = [e for rows in selected["own"].values() for e in rows] + selected["opponent"]
        self.assertFalse([e for e in positive if e.get("outcome") == "avoid"])
        self.assertTrue(all(e["tier"] in (1, 2) for rows in selected["own"].values() for e in rows))

    def test_role_preference(self):
        wolf = select_examples(self.examples, "人狼")["own"]["rebut"]
        villager = select_examples(self.examples, "村人")["own"]["rebut"]
        count = lambda rows, role: sum(1 for e in rows if e["role"] == role)
        self.assertGreaterEqual(count(wolf, "人狼"), count(villager, "人狼"))


if __name__ == "__main__":
    unittest.main()
