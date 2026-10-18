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


if __name__ == "__main__":
    unittest.main()
