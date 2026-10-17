import json
import unittest

from zinro_learn.analyze import speech_stats
from zinro_learn.parse import anonymize, build_mapping, parse_game

# 形式の確認用に作った架空のログ(実在のログではない)。新しい発言が上。
SAMPLE = """\
鯖: 人狼が全滅しました!【村人チーム】の勝利です!
鯖: 【投票結果】
アリス(0票)の投票先→カレン
ボブ(1票)の投票先→カレン
カレン(2票)の投票先→ボブ
投票の結果【カレン】さんが処刑されます
鯖: カレンさんが死亡しました
カレン→GM: 投票@カレン→ボブ
ボブ→GM: 投票@ボブ→カレン
アリス→GM: 投票@アリス→カレン
カレン→カレン: 結論は変わらない
鯖: 投票時間になりました。話すのをやめてください。
カレン: アリス: 本当ですか？
ミラ→霊界: 見てます
↑ここを読んでいる
ボブ: それは違うと思います。
続きの行です。
アリス: おはようございます。ボビーさん、カレンさんもよろしく
鯖: 時間を90秒延長しました
鯖: 恐ろしい夜が明け、朝になりました。
鯖: 初日犠牲者さんが死亡しました
鯖→人狼: 初日犠牲者さんを噛みます
人狼→GM: 実行@カレン→初日犠牲者
鯖: 夜になりました…役職の人は能力を実行してください
鯖: ゲームを開始します
鯖: 役職設定【人狼-1,村人-3,役欠け:あり】
鯖→アリス: あなたは【村人】です
鯖→初日犠牲者: あなたは【村人】です
鯖→カレン: あなたは【人狼】です
鯖→ボブ: あなたは【村人】です
"""

PARTIAL = "ボブ: こんにちは\n鯖→ボブ: あなたは【村人】です\n"

# 名前に「：」を含む人(RE：ハル)と、勝利の通知より後のゲーム後の雑談がある、架空のログ。
COLON_NAME = """\
鯖: ゲームを終了しました。お疲れさまでした。
ボブ: お疲れさまでした
RE：ハル: 勝てた：ありがとう
鯖: 人狼が全滅しました!【村人チーム】の勝利です!
鯖: 【投票結果】
ボブ(0票)の投票先→RE：ハル
RE：ハル(2票)の投票先→ボブ
アリス(0票)の投票先→RE：ハル
投票の結果【RE：ハル】さんが処刑されます
鯖: RE：ハルさんが死亡しました
アリス→GM: 投票@アリス→RE：ハル
RE：ハル→GM: 投票@RE：ハル→ボブ
ボブ→GM: 投票@ボブ→RE：ハル
鯖: 投票時間になりました。話すのをやめてください。
RE：ハル→霊界: 見ています
RE：ハル: ボブさん、どう思いますか？
アリス: ハルさんは怪しい
ボブ: 同じです。
鯖: 恐ろしい夜が明け、朝になりました。
鯖: 夜になりました…役職の人は能力を実行してください
鯖: ゲームを開始します
鯖: 役職設定【人狼-1,村人-2,役欠け:あり】
鯖→アリス: あなたは【村人】です
鯖→RE：ハル: あなたは【人狼】です
鯖→ボブ: あなたは【村人】です
"""


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.game = parse_game(SAMPLE, game_id="sample")
        self.events = self.game["events"]

    def speech(self, speaker):
        return [e for e in self.events if e["kind"] == "speech" and e["speaker"] == speaker]

    def test_order_is_detected_and_reversed(self):
        self.assertEqual(self.events[0]["kind"], "private")
        self.assertIn("勝利", self.events[-1]["text"])
        self.assertEqual([e["seq"] for e in self.events], list(range(1, len(self.events) + 1)))

    def test_undecidable_order_needs_explicit_option(self):
        with self.assertRaises(ValueError):
            parse_game(PARTIAL, game_id="partial")
        self.assertEqual(len(parse_game(PARTIAL, game_id="partial", order="newest-first")["events"]), 2)

    def test_players_setup_winner(self):
        self.assertEqual(self.game["players"]["カレン"], {"role": "人狼"})
        self.assertTrue(self.game["players"]["初日犠牲者"]["dummy"])
        self.assertEqual(self.game["setup"], "人狼-1,村人-3,役欠け:あり")
        self.assertEqual(self.game["winner"], "村人チーム")

    def test_continuation_lines_are_joined(self):
        self.assertEqual(self.speech("ボブ")[0]["text"], "それは違うと思います。\n続きの行です。")

    def test_colon_inside_speech_text(self):
        self.assertEqual(self.speech("カレン")[0]["text"], "アリス: 本当ですか？")

    def test_spirit_and_self_lines_are_not_speech(self):
        spirit = next(e for e in self.events if e["kind"] == "spirit")
        self.assertEqual((spirit["speaker"], spirit["text"]), ("ミラ", "見てます\n↑ここを読んでいる"))
        self.assertEqual(next(e for e in self.events if e["kind"] == "self")["speaker"], "カレン")
        self.assertEqual(len([e for e in self.events if e["kind"] == "speech"]), 3)
        self.assertEqual(self.speech("カレン")[0]["text"], "アリス: 本当ですか？")

    def test_phase_and_day(self):
        by_text = {e["text"]: e for e in self.events}
        night = by_text["夜になりました…役職の人は能力を実行してください"]
        self.assertEqual((night["phase"], night["day"]), ("night", 0))
        morning = by_text["恐ろしい夜が明け、朝になりました。"]
        self.assertEqual((morning["phase"], morning["day"]), ("day", 1))
        self.assertEqual(self.speech("アリス")[0]["phase"], "day")
        vote = by_text["投票時間になりました。話すのをやめてください。"]
        self.assertEqual((vote["phase"], vote["day"]), ("vote", 1))
        self.assertEqual(self.events[-1]["phase"], "end")

    def test_commands_votes_and_death(self):
        command = next(e for e in self.events if e.get("action") == "投票" and e["actor"] == "アリス")
        self.assertEqual(command["target"], "カレン")
        result = next(e for e in self.events if "votes" in e)
        self.assertEqual(result["executed"], "カレン")
        self.assertEqual(
            result["votes"][2], {"player": "カレン", "received": 2, "voted_for": "ボブ"}
        )
        self.assertEqual(next(e for e in self.events if e.get("death") == "初日犠牲者")["phase"], "night")


class ColonNameTest(unittest.TestCase):
    def setUp(self):
        self.game = parse_game(COLON_NAME, game_id="colon")
        self.events = self.game["events"]

    def test_name_with_colon_is_a_player(self):
        self.assertEqual(self.game["players"]["RE：ハル"], {"role": "人狼"})
        notice = next(e for e in self.events if e["kind"] == "private" and e["text"].startswith("あなたは【人狼"))
        self.assertEqual(notice["to"], "RE：ハル")

    def test_speech_and_spirit_lines_of_that_name(self):
        speech = [e for e in self.events if e["kind"] == "speech" and e["speaker"] == "RE：ハル"]
        self.assertEqual([e["text"] for e in speech], ["ボブさん、どう思いますか？"])
        spirit = next(e for e in self.events if e["kind"] == "spirit")
        self.assertEqual((spirit["speaker"], spirit["text"]), ("RE：ハル", "見ています"))

    def test_commands_and_vote_lines_of_that_name(self):
        votes = {e["actor"]: e["target"] for e in self.events if e["kind"] == "command"}
        self.assertEqual(votes, {"アリス": "RE：ハル", "RE：ハル": "ボブ", "ボブ": "RE：ハル"})
        result = next(e for e in self.events if "votes" in e)
        self.assertEqual(result["executed"], "RE：ハル")
        self.assertEqual(
            result["votes"][1], {"player": "RE：ハル", "received": 2, "voted_for": "ボブ"}
        )
        self.assertEqual(next(e for e in self.events if "death" in e)["death"], "RE：ハル")
        self.assertFalse([e for e in self.events if e["kind"] == "directed"])

    def test_after_game_talk_is_kept_apart_from_speech(self):
        after = [e for e in self.events if e["kind"] == "after"]
        self.assertEqual([e["speaker"] for e in after], ["RE：ハル", "ボブ"])
        self.assertEqual(after[0]["text"], "勝てた：ありがとう")
        self.assertTrue(all(e["phase"] == "end" for e in after))
        self.assertEqual(len([e for e in self.events if e["kind"] == "speech"]), 3)
        stats = speech_stats(anonymize(self.game, build_mapping(self.game)))
        self.assertEqual(stats["speech_messages"], 3)

    def test_anonymize_replaces_name_and_alias(self):
        mapping = build_mapping(self.game, {"RE：ハル": "C"})
        anonymized = anonymize(self.game, mapping, {"ハル": "RE：ハル"})
        dumped = json.dumps(anonymized, ensure_ascii=False)
        self.assertNotIn("ハル", dumped)
        self.assertEqual(mapping, {"RE：ハル": "C", "ボブ": "A", "アリス": "B"})
        speech = next(e for e in anonymized["events"] if e["kind"] == "speech" and e["speaker"] == "B")
        self.assertEqual(speech["text"], "《C》さんは怪しい")


class AnonymizeTest(unittest.TestCase):
    def setUp(self):
        self.game = parse_game(SAMPLE, game_id="sample")
        self.mapping = build_mapping(self.game)
        self.anonymized = anonymize(self.game, self.mapping, {"ボビー": "ボブ"})

    def test_mapping_follows_speaking_order_and_skips_dummy(self):
        self.assertEqual(self.mapping, {"アリス": "A", "ボブ": "B", "カレン": "C", "ミラ": "O1"})
        self.assertEqual(
            build_mapping(self.game, {"カレン": "A"}),
            {"カレン": "A", "アリス": "B", "ボブ": "C", "ミラ": "O1"},
        )

    def test_names_are_replaced_everywhere(self):
        dumped = json.dumps(self.anonymized, ensure_ascii=False)
        for name in ("アリス", "ボブ", "カレン", "ボビー", "ミラ"):
            self.assertNotIn(name, dumped)
        greeting = next(e for e in self.anonymized["events"] if e["speaker"] == "A" and e["kind"] == "speech")
        self.assertEqual(greeting["text"], "おはようございます。《B》さん、《C》さんもよろしく")
        self.assertEqual(self.anonymized["players"]["C"], {"role": "人狼"})
        self.assertIn("初日犠牲者", self.anonymized["players"])

    def test_unknown_alias_target_is_rejected(self):
        with self.assertRaises(ValueError):
            anonymize(self.game, self.mapping, {"ボビー": "いない人"})


class StatsTest(unittest.TestCase):
    def test_speech_stats(self):
        game = parse_game(SAMPLE, game_id="sample")
        anonymized = anonymize(game, build_mapping(game), {"ボビー": "ボブ"})
        stats = speech_stats(anonymized)
        self.assertEqual(stats["speech_messages"], 3)
        self.assertEqual(stats["speakers"]["A"]["mentions"], 2)
        self.assertEqual(stats["speakers"]["B"]["chars_max"], len("それは違うと思います。続きの行です。"))
        self.assertEqual(stats["speakers"]["C"]["questions"], 1)
        self.assertEqual(stats["speakers"]["C"]["role"], "人狼")
        self.assertEqual(sum(s["chars_total"] for s in stats["speakers"].values()), stats["chars_total"])

    def test_throughput_needs_discussion_seconds(self):
        game = parse_game(SAMPLE, game_id="sample")
        self.assertEqual(game["extension_seconds"], 90)
        self.assertNotIn("minutes", speech_stats(game))
        game["discussion_seconds"] = 150
        stats = speech_stats(anonymize(game, build_mapping(game)))
        self.assertEqual(stats["minutes"], 4.0)  # (150秒 × 1日 + 延長90秒) / 60
        self.assertEqual(stats["chars_per_minute"], round(stats["chars_total"] / 4.0, 1))
        self.assertEqual(stats["messages_per_minute"], round(stats["speech_messages"] / 4.0, 1))
        self.assertEqual(
            stats["speakers"]["A"]["chars_per_minute"], round(stats["speakers"]["A"]["chars_total"] / 4.0, 1)
        )


if __name__ == "__main__":
    unittest.main()
