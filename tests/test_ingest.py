import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from zinro_learn.__main__ import main, parse_names
from zinro_learn.check import private_names

# 取り込みの確認用に作った架空のログ(実在のログではない)。新しい発言が上。
# 人狼のハンドル名は「なるほどね」で、本文中の語句としても出る(ふつうの語句でもある名前の例)。
RAW = """\
鯖: 人狼が全滅しました!【村人チーム】の勝利です!
鯖: 【投票結果】
アリス(1票)の投票先→なるほどね
なるほどね(2票)の投票先→アリス
カレン(0票)の投票先→なるほどね
投票の結果【なるほどね】さんが処刑されます
鯖: なるほどねさんが死亡しました
鯖: 投票時間になりました。話すのをやめてください。
なるほどね: なるほどね、おはよう
アリス: おはよう
鯖: 恐ろしい夜が明け、朝になりました。
鯖: 初日犠牲者さんが死亡しました
鯖: 夜になりました…役職の人は能力を実行してください
鯖: ゲームを開始します
鯖: 役職設定【人狼-1,村人-3,役欠け:あり】
鯖→アリス: あなたは【村人】です
鯖→初日犠牲者: あなたは【村人】です
鯖→なるほどね: あなたは【人狼】です
鯖→カレン: あなたは【村人】です
"""
PLAYERS = "アリス=A,なるほどね=C,カレン=B"

# 人狼が2人いる架空のログ(実在のログではない)。人狼の役職通知には「　仲間は【…】です」が続き、夜に「名前→人狼:」でチャットする。
# 昼1に村人のアリスを処刑し、夜に村人のダンが噛まれて、人狼が村人の数より多くなる。
RAW_WOLVES = """\
鯖: 人狼が村人の数より多くなりました!【人狼チーム】の勝利です!
鯖: ダンさんが死亡しました
鯖→人狼: ダンさんを噛みます
人狼→GM: 実行@カレン→ダン
ボブ→人狼: 次はダンさんかな
鯖: 夜になりました…役職の人は能力を実行してください
鯖: 【投票結果】
アリス(4票)の投票先→ボブ
ボブ(1票)の投票先→アリス
カレン(0票)の投票先→アリス
ダン(0票)の投票先→アリス
エマ(0票)の投票先→アリス
投票の結果【アリス】さんが処刑されます
鯖: アリスさんが死亡しました
エマ→GM: 投票@エマ→アリス
ダン→GM: 投票@ダン→アリス
カレン→GM: 投票@カレン→アリス
ボブ→GM: 投票@ボブ→アリス
アリス→GM: 投票@アリス→ボブ
鯖: 投票時間になりました。話すのをやめてください。
カレン: エマさんが怪しい
ボブ: おはようございます
アリス: おはよう
鯖: 恐ろしい夜が明け、朝になりました。
鯖: 初日犠牲者さんが死亡しました
鯖→人狼: 初日犠牲者さんを噛みます
人狼→GM: 実行@ボブ→初日犠牲者
カレン→人狼: 初日は様子見で
ボブ→人狼: よろしく、カレンさん
鯖: 夜になりました…役職の人は能力を実行してください
鯖: ゲームを開始します
鯖: 役職設定【人狼-2,村人-4,役欠け:あり】
鯖→アリス: あなたは【村人】です
鯖→ボブ: あなたは【人狼】です　仲間は【カレン】です
鯖→カレン: あなたは【人狼】です　仲間は【ボブ】です
鯖→ダン: あなたは【村人】です
鯖→エマ: あなたは【村人】です
鯖→初日犠牲者: あなたは【村人】です
"""


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.raw = self.root / "raw.txt"
        self.raw.write_text(RAW, encoding="utf-8")
        self.table_path = self.root / "logs/private/g.players.json"

    def ingest(self, *options):
        argv = [
            "ingest", str(self.raw), "--id", "g", "--players", PLAYERS,
            "--out-dir", str(self.root / "logs/normalized"), "--private-dir", str(self.root / "logs/private"),
            "--discussion-seconds", "300", *options,
        ]
        with redirect_stdout(io.StringIO()):
            main(argv)
        return json.loads(self.table_path.read_text(encoding="utf-8"))

    def test_table_is_unchanged_in_shape_without_plain_words(self):
        table = self.ingest("--alias", "なる=なるほどね")
        self.assertEqual(set(table), {"players", "aliases"})  # 指定のないログの対応表は、これまでと同じ形
        self.assertEqual(table["players"], {"A": "アリス", "C": "なるほどね", "B": "カレン"})
        self.assertEqual(table["aliases"], {"なる": "なるほどね"})

    def test_plain_word_is_written_to_the_table(self):
        table = self.ingest("--plain-word", "なるほどね")
        self.assertEqual(table["plain_words"], ["なるほどね"])
        game = json.loads((self.root / "logs/normalized/g.json").read_text(encoding="utf-8"))
        self.assertEqual(game["winner"], "村人チーム")
        self.assertEqual(game["discussion_seconds"], 300)
        self.assertEqual(game["players"]["C"]["role"], "人狼")

    def test_plain_words_may_repeat_or_be_comma_separated(self):
        table = self.ingest("--plain-word", "なるほどね,アリス", "--plain-word", "なるほどね", "--plain-word", " アリス ")
        self.assertEqual(table["plain_words"], ["なるほどね", "アリス"])
        self.assertEqual(parse_names(["a,b", "b", ",c,"]), ["a", "b", "c"])

    def test_plain_word_may_name_an_alias(self):
        table = self.ingest("--alias", "なる=なるほどね", "--plain-word", "なる")
        self.assertEqual(table["plain_words"], ["なる"])

    def test_unknown_plain_word_is_rejected_before_anything_is_written(self):
        with self.assertRaises(ValueError):
            self.ingest("--plain-word", "いない人")
        self.assertFalse(self.table_path.exists())
        self.assertFalse((self.root / "logs/normalized/g.json").exists())

    def test_check_skips_plain_words_of_an_ingested_table(self):
        self.ingest("--plain-word", "なるほどね")
        self.assertEqual(private_names(self.root), {"アリス", "カレン"})  # 2文字以上の実名。plain_words は除く
        self.ingest()
        self.assertEqual(private_names(self.root), {"アリス", "カレン", "なるほどね"})


class WolvesIngestTest(unittest.TestCase):
    """人狼が2人のログ(仲間の通知、夜のチャット)を取り込む。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        raw = self.root / "raw.txt"
        raw.write_text(RAW_WOLVES, encoding="utf-8")
        self.normalized = self.root / "logs/normalized/w.json"
        argv = [
            "ingest", str(raw), "--id", "w", "--players", "アリス=C,ボブ=D,カレン=E,ダン=F,エマ=G",
            "--out-dir", str(self.root / "logs/normalized"), "--private-dir", str(self.root / "logs/private"),
        ]
        with redirect_stdout(io.StringIO()):
            main(argv)
        self.game = json.loads(self.normalized.read_text(encoding="utf-8"))

    def run_command(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            main(list(argv))
        return out.getvalue()

    def test_mates_and_wolf_chat_are_stored_with_anonymous_names(self):
        self.assertEqual(self.game["players"]["D"], {"role": "人狼", "mates": ["E"]})
        self.assertEqual(self.game["players"]["E"], {"role": "人狼", "mates": ["D"]})
        chat = [e for e in self.game["events"] if e["kind"] == "wolfchat"]
        self.assertEqual([(e["speaker"], e["text"]) for e in chat], [
            ("D", "よろしく、《E》さん"), ("E", "初日は様子見で"), ("D", "次は《F》さんかな"),
        ])
        self.assertEqual(self.game["winner"], "人狼チーム")
        self.assertNotIn("discussion_seconds", self.game)  # 議論時間を指定しなければ入らない
        dumped = json.dumps(self.game, ensure_ascii=False)
        for name in ("アリス", "ボブ", "カレン", "ダン", "エマ"):
            self.assertNotIn(name, dumped)
        table = json.loads((self.root / "logs/private/w.players.json").read_text(encoding="utf-8"))
        self.assertEqual(table["players"], {"C": "アリス", "D": "ボブ", "E": "カレン", "F": "ダン", "G": "エマ"})

    def test_stats_count_only_speech(self):
        report = self.run_command("stats", str(self.normalized))
        self.assertIn("発言 3 件", report)  # 昼1の発言だけ。夜のチャット3件は数えない
        self.assertNotIn("day 1:", report)  # 議論が1日のログの出力は、これまでと同じ
        self.assertNotIn("字/分", report)  # 議論時間を指定しないので、字/分は出ない

    def test_timeline_prints_roles_nights_and_wolf_chat(self):
        report = self.run_command("timeline", str(self.normalized))
        for line in (
            "人狼のまとまり: D E", "夜0:", "噛み: D(人狼) → 初日犠牲者", "人狼チャット: 2 件", "昼1: 生存 5 人",
            "処刑: C (4票)", "夜1:", "噛み: E(人狼) → F", "人狼チャット: 1 件", "死亡: F (襲撃)",
        ):
            self.assertIn(line, report)


if __name__ == "__main__":
    unittest.main()
