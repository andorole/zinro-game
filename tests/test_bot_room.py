import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from zinro_bot.prompt import TIMED_FORMAT, as_text, build_system
from zinro_bot.room import MARKER, ROLES, build_prompts, build_room, casual_prompt

ROOT = Path(__file__).resolve().parent.parent


def embedded(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="prompts">(.*?)</script>', html, re.S)
    assert match, "prompts の script がない"
    return json.loads(match.group(1).replace("<\\/", "</"))


class RoomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = build_room(ROOT)

    def test_page_starts_with_its_title_and_has_no_document_skeleton(self):
        self.assertTrue(self.html.lstrip().startswith("<title>4A練習ルーム</title>"))
        lowered = self.html.lower()
        self.assertNotIn("<!doctype", lowered)
        self.assertIsNone(re.search(r"<(html|head|body)[\s>]", lowered))  # <header> は構わない
        self.assertNotIn(MARKER, self.html)

    def test_prompts_are_embedded_per_role(self):
        data = embedded(self.html)
        self.assertEqual(set(data), {"strong", "casual", "judge"})
        for role in ROLES:
            strong, casual = data["strong"][role], data["casual"][role]
            self.assertIn(f"役職は{role}", strong)
            self.assertIn(f"役職は{role}", casual)
            for text in (strong, casual):
                self.assertIn("{me}", text)  # 名前と語調は、ページが実行時に置き換える
                self.assertIn("{register}", text)
                self.assertNotIn("{role}", text)
            self.assertIn("出力形式(練習部屋)", strong)
            self.assertIn("1行に1つの JSON", strong)
            self.assertIn("1行に1つの JSON", casual)

    def test_the_strong_prompt_keeps_the_knowledge_and_drops_the_paste_flow(self):
        strong = embedded(self.html)["strong"]["村人"]
        self.assertIn("両論で止めない", strong)  # 両論で止めず、吊り先は終盤まで出さない
        self.assertIn("「誰が狼か」の結論と、吊り先は、終盤", strong)
        self.assertIn("挨拶は、ゲームが始まったらすぐ、最初に言う", strong)  # 遅れて挨拶しない
        self.assertNotIn("雑談と議論の切り替え、", strong)
        self.assertNotIn("雑談が10件以上続いて", strong)  # 雑談から議論への切り替えを求めない
        self.assertIn("相手が答えた(答えようとした)問いは、聞き直さない", strong)  # 蒸し返さない
        self.assertIn("票先への言及は、毎回しない", strong)  # 票先は、言う価値があるときだけ
        self.assertIn("全員を同じ強さで見る", strong)  # 1人だけを攻めない
        self.assertIn("他の人と同じ相手を、同じ理由で、重ねて攻めない", strong)
        self.assertIn("# 発言例", strong)
        self.assertIn("ここは練習部屋。あなたの発言は、そのままチャットに表示される。", strong)
        self.assertNotIn("投稿するのは人間", strong)
        self.assertNotIn('"posts": [', strong)  # API 用の JSON 形式は残さない

    def test_script_close_tags_are_escaped_inside_the_json(self):
        match = re.search(r'<script type="application/json" id="prompts">(.*?)</script>', self.html, re.S)
        self.assertNotIn("</", match.group(1))

    def test_timed_output_format_replaces_the_json_format_only_for_timed(self):
        timed = build_system(ROOT, "ブン", "村人", "タメ口", output_format="timed")[0]["text"]
        plain = build_system(ROOT, "ブン", "村人", "タメ口")[0]["text"]
        self.assertIn(TIMED_FORMAT.splitlines()[0], timed)
        self.assertNotIn("練習部屋", plain.split("# 型の一覧")[0].split("## 11.")[-1])
        self.assertIn('"silence"', plain)

    def test_the_room_shows_more_conversational_examples(self):
        plain = as_text(build_system(ROOT, "{me}", "村人", "{register}", output_format="timed"))
        room = embedded(self.html)["strong"]["村人"]
        self.assertGreater(len(room), len(plain))

    def test_the_judge_prompt_is_neutral_and_has_the_deciding_vote(self):
        judge = embedded(self.html)["judge"]
        self.assertEqual(set(judge), {"村人"})  # 判定役は、人狼にならない
        text = judge["村人"]
        self.assertIn("どちらにも肩入れしない", text)
        self.assertIn("あなたの1票が、決め手になる", text)
        self.assertIn("口の巧さ、発言量、自信の強さ、先に言ったかどうか、押しの強さでは決めない", text)
        # 「答えなかったから狼」という独自の基準に寄らない。1つの基準で決めず、普通の材料を総合する
        self.assertIn("「答えなかった」「答えられなかった」ことだけで、人狼とは見ない", text)
        self.assertIn("自分だけの基準や理論を作らない", text)
        self.assertIn("判定役は、答えを催促しない", text)
        self.assertNotIn("答えのない問いが残っているとき", text)
        self.assertIn("1行に1つの JSON", text)
        self.assertIn("{me}", text)
        self.assertIn("{register}", text)
        self.assertIn("内部の番号(#12 など)は書かない", text)

    def test_casual_prompt_fills_the_role_only(self):
        text = casual_prompt("人狼")
        self.assertIn("役職は人狼", text)
        self.assertIn("{me}", text)
        self.assertIn("内部の番号(#12 など)は書かない", text)  # 実戦のチャットには、発言の番号がない
        self.assertIn("相手が答えた問いは、聞き直さない", text)
        self.assertIn("自分以外の全員を、同じ強さで見る。1人だけを攻めない", text)
        self.assertIn("議論全体で2回まで", text)
        self.assertEqual(set(build_prompts(ROOT)["casual"]), set(ROLES))

    @unittest.skipUnless(shutil.which("node"), "node がない")
    def test_page_script_parses(self):
        script = re.findall(r"<script>(.*?)</script>", self.html, re.S)[-1]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "room.js"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
