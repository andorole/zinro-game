import json
import unittest

from zinro_learn.analyze import discussion_days, extension_by_day, format_stats, speech_stats
from zinro_learn.parse import (
    ROLE_NOTICE, anonymize, build_mapping, collect_mates, directed, observer_names, parse_game, split_mates,
)
from zinro_learn.roles import (
    alive_by_day, deaths, format_timeline, is_wolfchat, night_actions, notices, plain, wolf_teams, wolfchat_summary,
)

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


def newest_first(*messages: str) -> str:
    """時間順に並べた発言(複数行の発言は1要素)を、貼り付けたままの形(新しい発言が上)に直す。"""
    return "\n".join(reversed(messages)) + "\n"


# 占い入りの6A(昼1 → 夜 → 昼2の2日かかる)の形を確かめる、架空のログ(実在のログではない)。
# ハンドル名「なるほどね」の人は、ふつうの語句でもある名前の例(本文中の「なるほどね」は語句)。
SEER = newest_first(
    "鯖→アリス: あなたは【村人】です",
    "鯖→ボブ: あなたは【占い師】です",
    "鯖→カレン: あなたは【人狼】です",
    "鯖→なるほどね: あなたは【村人】です",
    "鯖→ミラ: あなたは【村人】です",
    "鯖→初日犠牲者: あなたは【村人】です",
    "鯖: 役職設定【人狼-1,占い師-1,村人-4,役欠け:なし】",
    "鯖: ゲームを開始します",
    "鯖: 夜になりました…役職の人は能力を実行してください",
    "ボブ→GM: 実行@ボブ→アリス",
    "鯖→ボブ: アリスさんは人狼ではありません",
    "初日犠牲者→GM: 実行@初日犠牲者→ミラ",
    "ミラ→ミラ: 初日は何も起きないのかな",
    "人狼→GM: 実行@カレン→初日犠牲者",
    "鯖→人狼: 初日犠牲者さんを噛みます",
    "鯖: 初日犠牲者さんが死亡しました",
    "鯖: 恐ろしい夜が明け、朝になりました。",
    "アリス: おはようございます",
    "ボブ: おはよう（占いCO)アリス白",
    "鯖: 時間を90秒延長しました",
    "鯖: 時間を90秒延長しました",
    "なるほどね: なるほどね、じゃあボブさんを信じる\n吊り先はミラさんかカレンさんかな",
    "カレン: ミラさんが怪しいと思います",
    "ユキ→霊界: 観戦しています",
    "鯖: 投票時間になりました。話すのをやめてください。",
    "アリス→GM: 投票@アリス→ミラ",
    "ボブ→GM: 投票@ボブ→ミラ",
    "カレン→GM: 投票@カレン→ミラ",
    "ミラ→GM: 投票@ミラ→カレン",
    "なるほどね→GM: 投票@なるほどね→ミラ",
    "鯖: ミラさんが死亡しました",
    "鯖: 【投票結果】\n"
    "アリス(0票)の投票先→ミラ\n"
    "ボブ(0票)の投票先→ミラ\n"
    "カレン(1票)の投票先→ミラ\n"
    "ミラ(4票)の投票先→カレン\n"
    "なるほどね(0票)の投票先→ミラ\n"
    "投票の結果【ミラ】さんが処刑されます",
    "鯖: 夜になりました…役職の人は能力を実行してください",
    "ボブ→GM: 実行@ボブ→カレン",
    "鯖→ボブ: カレンさんは人狼です",
    "ユキ→霊界: 占い師が噛まれそう",
    "人狼→GM: 実行@カレン→ボブ",
    "鯖→人狼: ボブさんを噛みます",
    "鯖: ボブさんが死亡しました",
    "鯖: 恐ろしい夜が明け、朝になりました。",
    "アリス: ボブさんの結果が聞けなかったね",
    "鯖: 時間を90秒延長しました",
    "カレン: アリスさんと、なるほどねさんなら、どっちを吊りますか？",
    "なるほどね: カレンさんでいい",
    "鯖: 投票時間になりました。話すのをやめてください。",
    "アリス→GM: 投票@アリス→カレン",
    "カレン→GM: 投票@カレン→アリス",
    "なるほどね→GM: 投票@なるほどね→カレン",
    "鯖: カレンさんが死亡しました",
    "鯖: 【投票結果】\n"
    "アリス(0票)の投票先→カレン\n"
    "カレン(2票)の投票先→アリス\n"
    "なるほどね(0票)の投票先→カレン\n"
    "投票の結果【カレン】さんが処刑されます",
    "鯖: 人狼が全滅しました!【村人チーム】の勝利です!",
)


# 人狼が2人・占い師・霊能者・狩人のいる8人村(初日犠牲者を含む)で、昼1・昼2・昼3の3日かかる、架空のログ(実在のログではない)。
# 人狼の役職通知には「　仲間は【…】です」(全角空白)が続き、人狼どうしは夜に「名前→人狼:」でチャットする。
# 初日の占いは黒(カレン)で、昼1に処刑される。昼2は村人のミラを処刑し、昼3に最後の人狼ダンを処刑する。
TEAM = newest_first(
    "鯖→アリス: あなたは【村人】です",
    "鯖→ボブ: あなたは【占い師】です",
    "鯖→カレン: あなたは【人狼】です　仲間は【ダン】です",
    "鯖→ダン: あなたは【人狼】です　仲間は【カレン】です",
    "鯖→エマ: あなたは【霊能者】です",
    "鯖→フィル: あなたは【狩人】です",
    "鯖→ミラ: あなたは【村人】です",
    "鯖→初日犠牲者: あなたは【村人】です",
    "鯖: 役職設定【人狼-2,占い師-1,狩人-1,霊能者-1,村人-3,役欠け:あり】",
    "鯖: ゲームを開始します",
    "鯖: 夜になりました…役職の人は能力を実行してください",
    "初日犠牲者→GM: 実行@初日犠牲者→ミラ",
    "フィル→GM: 実行@フィル→ボブ",
    "ユキ→霊界: 見ています",
    "カレン→人狼: 占いを騙るのはダンにしよう",
    "ダン→人狼: 了解\nカレンさんの黒が出たらどうする？",
    "ボブ→GM: 実行@ボブ→カレン",
    "鯖→ボブ: カレンさんは人狼です",
    "ボブ→ボブ: 初日から黒が出た",
    "人狼→GM: 実行@カレン→初日犠牲者",
    "鯖→人狼: 初日犠牲者さんを噛みます",
    "鯖: 初日犠牲者さんが死亡しました",
    "鯖: 恐ろしい夜が明け、朝になりました。",
    "アリス: おはよう",
    "ダン: 【占いco:アリス〇】",
    "ボブ: 【占いRCO】カレンさん→黒",
    "エマ: 【霊能CO】",
    "カレン: 村人です",
    "鯖: 時間を90秒延長しました",
    "鯖: 時間を90秒延長しました",
    "ミラ: カレンさんを吊ろう",
    "鯖: 投票時間になりました。話すのをやめてください。",
    "アリス→GM: 投票@アリス→カレン",
    "ボブ→GM: 投票@ボブ→カレン",
    "カレン→GM: 投票@カレン→ボブ",
    "ダン→GM: 投票@ダン→ボブ",
    "エマ→GM: 投票@エマ→カレン",
    "フィル→GM: 投票@フィル→カレン",
    "ミラ→GM: 投票@ミラ→カレン",
    "鯖: カレンさんが死亡しました",
    "鯖→エマ: 処刑されたカレンさんは人狼です",
    "鯖: 【投票結果】\n"
    "アリス(0票)の投票先→カレン\n"
    "ボブ(2票)の投票先→カレン\n"
    "カレン(5票)の投票先→ボブ\n"
    "ダン(0票)の投票先→ボブ\n"
    "エマ(0票)の投票先→カレン\n"
    "フィル(0票)の投票先→カレン\n"
    "ミラ(0票)の投票先→カレン\n"
    "投票の結果【カレン】さんが処刑されます",
    "鯖: 夜になりました…役職の人は能力を実行してください",
    "フィル→GM: 実行@フィル→エマ",
    "ダン→人狼: ひとりになった",
    "ボブ→GM: 実行@ボブ→アリス",
    "鯖→ボブ: アリスさんは人狼ではありません",
    "人狼→GM: 実行@ダン→ボブ",
    "鯖→人狼: ボブさんを噛みます",
    "鯖: ボブさんが死亡しました",
    "鯖: 恐ろしい夜が明け、朝になりました。",
    "エマ: 【●】",
    "ボブ→霊界: 噛まれた",
    "ダン: ボブさんは本物だったんですね",
    "アリス: ミラさんが怪しいと思う",
    "鯖: 投票時間になりました。話すのをやめてください。",
    "アリス→GM: 投票@アリス→ミラ",
    "エマ→GM: 投票@エマ→ミラ",
    "フィル→GM: 投票@フィル→ミラ",
    "ダン→GM: 投票@ダン→フィル",
    "ミラ→GM: 投票@ミラ→ダン",
    "鯖: ミラさんが死亡しました",
    "鯖→エマ: 処刑されたミラさんは人狼ではありません",
    "鯖: 【投票結果】\n"
    "アリス(0票)の投票先→ミラ\n"
    "エマ(0票)の投票先→ミラ\n"
    "フィル(1票)の投票先→ミラ\n"
    "ダン(1票)の投票先→フィル\n"
    "ミラ(3票)の投票先→ダン\n"
    "投票の結果【ミラ】さんが処刑されます",
    "鯖: 夜になりました…役職の人は能力を実行してください",
    "フィル→GM: 実行@フィル→エマ",
    "ダン→人狼: あと少し",
    "人狼→GM: 実行@ダン→フィル",
    "鯖→人狼: フィルさんを噛みます",
    "鯖: フィルさんが死亡しました",
    "鯖: 恐ろしい夜が明け、朝になりました。",
    "鯖: 時間を90秒延長しました",
    "アリス: ダンさんで決まりだと思う",
    "ダン: 【狼CO】",
    "鯖: 投票時間になりました。話すのをやめてください。",
    "アリス→GM: 投票@アリス→ダン",
    "エマ→GM: 投票@エマ→ダン",
    "ダン→GM: 投票@ダン→アリス",
    "鯖: ダンさんが死亡しました",
    "鯖→エマ: 処刑されたダンさんは人狼です",
    "鯖: 【投票結果】\n"
    "アリス(1票)の投票先→ダン\n"
    "エマ(0票)の投票先→ダン\n"
    "ダン(2票)の投票先→アリス\n"
    "投票の結果【ダン】さんが処刑されます",
    "鯖: 人狼が全滅しました!【村人チーム】の勝利です!",
)


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


class SeerGameTest(unittest.TestCase):
    """占い師のいる6A。昼1 → 夜 → 昼2の2日かかり、投票結果が2回出る。"""

    def setUp(self):
        self.game = parse_game(SEER, game_id="seer")
        self.events = self.game["events"]

    def event(self, kind, text, **fields):
        return next(e for e in self.events if e["kind"] == kind and text in e["text"] and all(e.get(k) == v for k, v in fields.items()))

    def test_order_setup_and_roles(self):
        self.assertEqual(self.events[0]["kind"], "private")
        self.assertEqual(self.events[-1]["phase"], "end")
        self.assertEqual(self.game["setup"], "人狼-1,占い師-1,村人-4,役欠け:なし")
        self.assertEqual(self.game["players"]["ボブ"], {"role": "占い師"})
        self.assertTrue(self.game["players"]["初日犠牲者"]["dummy"])
        self.assertEqual(self.game["winner"], "村人チーム")

    def test_phase_and_day_over_two_days(self):
        first_night = self.event("command", "ボブ→アリス")
        self.assertEqual((first_night["phase"], first_night["day"]), ("night", 0))
        mornings = [e for e in self.events if "朝になりました" in e["text"]]
        self.assertEqual([(e["phase"], e["day"]) for e in mornings], [("day", 1), ("day", 2)])
        votes = [e for e in self.events if "投票時間になりました" in e["text"]]
        self.assertEqual([(e["phase"], e["day"]) for e in votes], [("vote", 1), ("vote", 2)])
        second_night = self.event("command", "ボブ→カレン")
        self.assertEqual((second_night["phase"], second_night["day"]), ("night", 1))
        speech = [e for e in self.events if e["kind"] == "speech"]
        self.assertEqual({(e["phase"], e["day"]) for e in speech}, {("day", 1), ("day", 2)})
        self.assertEqual(discussion_days(self.game), 2)

    def test_divination_notices_and_commands(self):
        white = self.event("private", "アリスさんは人狼ではありません")
        black = self.event("private", "カレンさんは人狼です")
        self.assertEqual((white["to"], white["phase"], white["day"]), ("ボブ", "night", 0))
        self.assertEqual((black["to"], black["phase"], black["day"]), ("ボブ", "night", 1))
        self.assertIsNone(white["speaker"])
        seer_commands = [
            (e["day"], e["target"]) for e in self.events
            if e["kind"] == "command" and e["actor"] == "ボブ" and e["action"] == "実行"
        ]
        self.assertEqual(seer_commands, [(0, "アリス"), (1, "カレン")])
        wolf = self.event("command", "カレン→ボブ")
        self.assertEqual((wolf["speaker"], wolf["actor"], wolf["target"]), ("人狼", "カレン", "ボブ"))
        dummy = self.event("command", "初日犠牲者→ミラ")
        self.assertEqual((dummy["actor"], dummy["target"]), ("初日犠牲者", "ミラ"))
        # 能力の行・結果の通知・独り言・霊界は、どれも発言として数えない
        self.assertEqual(len([e for e in self.events if e["kind"] == "speech"]), 7)

    def test_two_vote_results_and_deaths(self):
        results = [e for e in self.events if "votes" in e]
        self.assertEqual([e["executed"] for e in results], ["ミラ", "カレン"])
        self.assertEqual([e["day"] for e in results], [1, 2])
        self.assertIn({"player": "ミラ", "received": 4, "voted_for": "カレン"}, results[0]["votes"])
        self.assertEqual(len(results[1]["votes"]), 3)
        deaths = [(e["death"], e["phase"], e["day"]) for e in self.events if "death" in e]
        self.assertEqual(
            deaths,
            [("初日犠牲者", "night", 0), ("ミラ", "vote", 1), ("ボブ", "night", 1), ("カレン", "vote", 2)],
        )

    def test_spirit_talk_stays_out_of_speech(self):
        spirits = [e for e in self.events if e["kind"] == "spirit"]
        self.assertEqual([e["phase"] for e in spirits], ["day", "night"])
        self.assertEqual(observer_names(self.game), ["ユキ"])

    def test_extension_is_counted_in_total_and_by_day(self):
        self.assertEqual(self.game["extension_seconds"], 270)
        self.assertEqual(extension_by_day(self.game), {1: 180, 2: 90})

    def test_plain_handle_is_replaced_everywhere_in_the_text(self):
        mapping = build_mapping(self.game, {"なるほどね": "C"})
        anonymized = anonymize(self.game, mapping)
        speech = next(e for e in anonymized["events"] if e["kind"] == "speech" and e["speaker"] == "C")
        # 本文中の語句としての「なるほどね」も、名前と区別できないので置き換わる(読むときは前後で見分ける)
        self.assertTrue(speech["text"].startswith("《C》、じゃあ"))
        self.assertNotIn("なるほどね", json.dumps(anonymized, ensure_ascii=False))

    def test_discussion_minutes_cover_both_days(self):
        self.game["discussion_seconds"] = 300
        stats = speech_stats(anonymize(self.game, build_mapping(self.game)))
        self.assertEqual(stats["minutes"], 14.5)  # (300秒 × 2日 + 延長270秒) / 60
        self.assertEqual(stats["chars_per_minute"], round(stats["chars_total"] / 14.5, 1))
        self.assertEqual(stats["messages_per_minute"], round(7 / 14.5, 1))

    def test_breakdown_by_day(self):
        self.game["discussion_seconds"] = 300
        stats = speech_stats(anonymize(self.game, build_mapping(self.game)))
        first, second = stats["days"]
        self.assertEqual((first["day"], first["seconds"], first["messages"]), (1, 480, 4))  # 300 + 90 × 2
        self.assertEqual((second["day"], second["seconds"], second["messages"]), (2, 390, 3))  # 300 + 90 × 1
        self.assertEqual(first["messages"] + second["messages"], stats["speech_messages"])
        self.assertEqual(first["chars"] + second["chars"], stats["chars_total"])
        self.assertEqual(first["chars_per_minute"], round(first["chars"] / 8, 1))
        self.assertEqual(second["chars_per_minute"], round(second["chars"] / 6.5, 1))
        self.assertEqual(sum(d["speakers"]["C"]["messages"] for d in stats["days"]), stats["speakers"]["C"]["messages"])
        report = format_stats(stats)
        self.assertIn("day 1: 発言 4 件", report)
        self.assertIn("day 2: 発言 3 件", report)

    def test_breakdown_needs_two_days_and_discussion_seconds(self):
        self.assertNotIn("seconds", speech_stats(anonymize(self.game, build_mapping(self.game)))["days"][0])
        single = parse_game(SAMPLE, game_id="sample")
        single["discussion_seconds"] = 150
        stats = speech_stats(anonymize(single, build_mapping(single)))
        self.assertNotIn("days", stats)  # 1日のゲームの出力は、これまでと同じ
        self.assertNotIn("day 1:", format_stats(stats))


if __name__ == "__main__":
    unittest.main()
