import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from zinro_bot.__main__ import format_result, main
from zinro_bot.engine import Result
from zinro_bot.validate import Draft, Turn

ROOT = Path(__file__).resolve().parent.parent
# 新しい発言が上: こんにちは(ボブ) → おはよう(アリス) → よろしく(アリス)
LOG = "アリス: よろしく\nアリス: おはよう\nボブ: こんにちは\n鯖: 恐ろしい夜が明け、朝になりました。\n鯖→ボブ: あなたは【村人】です\n"


def run(*argv):
    out = io.StringIO()
    with redirect_stdout(out):
        main(["--root", str(ROOT), *argv])
    return out.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "log.txt"
        self.log.write_text(LOG, encoding="utf-8")

    def test_reply_with_the_fake_client(self):
        out = run("reply", str(self.log), "--fake")
        self.assertIn("■ 投稿案", out)
        self.assertIn("アリスは、どういう根拠でそう思うの？", out)

    def test_plain_and_dry_run(self):
        self.assertEqual(run("reply", str(self.log), "--fake", "--plain").strip(), "アリスは、どういう根拠でそう思うの？")
        self.assertIn("システムプロンプト:", run("reply", str(self.log), "--dry-run"))

    def test_show_transcript(self):
        self.assertIn("#1 ボブ: こんにちは", run("reply", str(self.log), "--show-transcript"))

    def test_prompt_command_writes_a_file(self):
        target = Path(self.tmp.name) / "p.txt"
        run("prompt", "--me", "ボブ", "--role", "村人", "--out", str(target))
        self.assertIn("プレイヤー「ボブ」", target.read_text(encoding="utf-8"))

    def test_format_result(self):
        turn = Turn({"aim": "詰める", "players": {"アリス": "疑い"}}, [Draft("根拠は？", [2], ["probe"])], "アリス", "")
        text = format_result(Result(turn))
        self.assertIn("[1] (返信先 #2 / probe)", text)
        self.assertIn("投票先: アリス", text)
        silent = format_result(Result(Turn({}, [], None, "材料がない")))
        self.assertIn("今は書かない: 材料がない", silent)


if __name__ == "__main__":
    unittest.main()
