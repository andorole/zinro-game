import unittest

from zinro_bot.transcript import parse_table, render

# 形式の確認用に作った架空の、対戦中のログ。新しい発言が上。自分(ボブ)の役職通知だけがある。
LIVE = """\
カレン: ボブさんの言う通りだと思います。
続きの行です。
例: これは見出しなので発言者ではない
アリス: そうなんですか？
ボブ: 本当ですか？
鯖: 時間を90秒延長しました
アリス: おはようございます
鯖: 恐ろしい夜が明け、朝になりました。
鯖: ゲームを開始します
鯖→ボブ: あなたは【村人】です
"""

OLDEST_FIRST = """\
鯖→ボブ: あなたは【人狼】です
鯖: ゲームを開始します
鯖: 恐ろしい夜が明け、朝になりました。
アリス: おはよう
ボブ: おはよう
カレン: よろしく
鯖: 投票時間になりました。話すのをやめてください。
"""


class ParseTableTest(unittest.TestCase):
    def test_live_log_newest_first(self):
        table = parse_table(LIVE)
        self.assertEqual((table.me, table.role), ("ボブ", "村人"))
        self.assertEqual([(p.seq, p.speaker) for p in table.posts],
                         [(1, "アリス"), (2, "ボブ"), (3, "アリス"), (4, "カレン")])
        self.assertEqual(table.posts[3].text, "ボブさんの言う通りだと思います。\n続きの行です。\n例: これは見出しなので発言者ではない")
        self.assertEqual(table.phase, "day")
        self.assertEqual(table.extensions, 1)

    def test_oldest_first_is_detected_and_vote_phase_is_found(self):
        table = parse_table(OLDEST_FIRST)
        self.assertEqual([p.speaker for p in table.posts], ["アリス", "ボブ", "カレン"])
        self.assertEqual((table.me, table.role, table.phase), ("ボブ", "人狼", "vote"))

    def test_names_seen_once_are_kept_with_a_warning(self):
        table = parse_table("カレン: 初めまして\nボブ: こんにちは\nアリス: おはよう\nアリス: こんにちは\n鯖: 恐ろしい夜が明け、朝になりました。\n", me="ボブ", role="村人")
        self.assertIn("カレン", [p.speaker for p in table.posts])
        self.assertTrue(any("カレン" in w for w in table.warnings))

    def test_explicit_players_are_used_as_given(self):
        text = "鯖: 恐ろしい夜が明け、朝になりました。\nお嬢様: ごきげんよう\n"
        table = parse_table(text, me="ボブ", role="村人", players=["お嬢様"], order="oldest-first")
        self.assertEqual([(p.speaker, p.text) for p in table.posts], [("お嬢様", "ごきげんよう")])

    def test_own_command_and_spirit_lines_are_ignored(self):
        text = "ボブ→GM: 投票@ボブ→アリス\nアリス→霊界: 見てます\nアリス: どうも\nアリス: よろしく\n鯖→ボブ: あなたは【村人】です\n"
        table = parse_table(text)
        self.assertEqual([p.text for p in table.posts], ["よろしく", "どうも"])
        self.assertIn("アリス", table.players)

    def test_missing_me_and_role_are_warned(self):
        table = parse_table("アリス: おはよう\nカレン: どうも\nアリス: よろしく\n")
        self.assertTrue(any("自分の名前" in w for w in table.warnings))
        self.assertTrue(any("並び順" in w for w in table.warnings))

    def test_render_lists_posts_with_numbers_and_notices(self):
        out = render(parse_table(LIVE), remaining=200)
        self.assertIn("自分の名前: ボブ", out)
        self.assertIn("残り時間: 200秒", out)
        self.assertIn("#1 アリス: おはようございます", out)
        self.assertLess(out.index("[通知] 時間を90秒延長しました"), out.index("#2 ボブ: 本当ですか？"))
        self.assertIn("    続きの行です。", out)

    def test_empty_log(self):
        out = render(parse_table("鯖→ボブ: あなたは【人狼】です\n鯖: 恐ろしい夜が明け、朝になりました。\n"))
        self.assertIn("まだ誰も発言していない", out)


if __name__ == "__main__":
    unittest.main()
