import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zinro_bot import llm
from zinro_bot.engine import Context, feedback, hints, respond, user_message
from zinro_bot.transcript import parse_table

LOG = """\
カレン: ボブさんはどう思いますか？
アリス: それは違うと思います。
ボブ: こんにちは
アリス: おはよう
鯖: 恐ろしい夜が明け、朝になりました。
鯖→ボブ: あなたは【村人】です
"""

CTX = Context(system=[{"type": "text", "text": "指示"}], known_moves={"rebut", "probe"}, examples=[])


def good(text="根拠を聞きたい。"):
    return {"read": {"aim": "聞く"}, "posts": [{"reply_to": [3], "moves": ["probe"], "text": text}], "vote": None, "silence": ""}


class HintsTest(unittest.TestCase):
    def test_pending_questions_and_mentions_are_listed(self):
        table = parse_table(LOG)
        text = hints(table)
        self.assertIn("自分の最後の発言: #2", text)
        self.assertIn("自分の名前が出ている発言(最後の発言以降): #4", text)
        self.assertIn("問いを含む発言(最後の発言以降): #4", text)
        self.assertIn("文字量の割合", text)

    def test_empty_table(self):
        self.assertIn("まだ誰も発言していない", hints(parse_table("鯖→ボブ: あなたは【村人】です\n")))

    def test_user_message_contains_state_and_hints(self):
        message = user_message(parse_table(LOG), remaining=120)
        self.assertIn("残り時間: 120秒", message)
        self.assertIn("機械的に拾ったメモ", message)


class RespondTest(unittest.TestCase):
    def test_valid_first_try(self):
        client = llm.ScriptedClient([good()])
        result = respond(client, CTX, parse_table(LOG))
        self.assertEqual((result.attempts, [p.text for p in result.turn.posts]), (1, ["根拠を聞きたい。"]))

    def test_retries_with_the_reason_then_succeeds(self):
        client = llm.ScriptedClient([good("つまり違う。"), good("どこが違う？")])
        result = respond(client, CTX, parse_table(LOG))
        self.assertEqual((result.attempts, [p.text for p in result.turn.posts]), (2, ["どこが違う？"]))
        _, messages = client.calls[1]
        self.assertEqual(messages[-1]["content"][0]["type"], "tool_result")
        self.assertTrue(messages[-1]["content"][0]["is_error"])
        self.assertIn("つまり", messages[-1]["content"][0]["content"])

    def test_gives_up_and_drops_after_the_retries(self):
        client = llm.ScriptedClient([good("つまり違う。")] * 3)
        result = respond(client, CTX, parse_table(LOG), max_retries=2)
        self.assertEqual((result.attempts, result.turn.posts), (3, []))
        self.assertTrue(result.turn.problems)

    def test_feedback_lists_problems(self):
        client = llm.ScriptedClient([good("つまり違う。")])
        result = respond(client, CTX, parse_table(LOG), max_retries=0)
        self.assertIn("- 投稿1", feedback(result.turn))


class ClientTest(unittest.TestCase):
    def test_body_forces_the_tool_unless_thinking(self):
        client = llm.AnthropicClient(api_key="k", model="m")
        body = client.body([{"type": "text", "text": "s"}], [{"role": "user", "content": "u"}])
        self.assertEqual(body["tool_choice"], {"type": "tool", "name": llm.TOOL_NAME})
        self.assertEqual(body["tools"][0]["name"], llm.TOOL_NAME)
        thinking = llm.AnthropicClient(api_key="k", model="m", thinking_budget=2000).body([], [])
        self.assertEqual(thinking["tool_choice"], {"type": "auto"})
        self.assertGreater(thinking["max_tokens"], 2000)

    def test_extract_prefers_the_tool_and_falls_back_to_text_json(self):
        content = [{"type": "text", "text": "考え中"}, {"type": "tool_use", "id": "t1", "name": llm.TOOL_NAME, "input": {"posts": []}}]
        self.assertEqual(llm.extract(content), ({"posts": []}, "t1"))
        self.assertEqual(llm.extract([{"type": "text", "text": '前置き {"posts": [1]} 後ろ'}]), ({"posts": [1]}, None))
        with self.assertRaises(llm.ApiError):
            llm.extract([{"type": "text", "text": "JSON なし"}])

    def test_complete_sends_headers_and_parses_the_reply(self):
        payload = {"content": [{"type": "tool_use", "id": "t9", "name": llm.TOOL_NAME, "input": good()}], "usage": {"input_tokens": 5}}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        client = llm.AnthropicClient(api_key="secret", model="m", base_url="https://example.test/")
        with mock.patch("urllib.request.urlopen", return_value=Response()) as urlopen:
            reply = client.complete([{"type": "text", "text": "s"}], [{"role": "user", "content": "u"}])
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, "https://example.test/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "secret")
        self.assertEqual(request.get_header("Anthropic-version"), llm.API_VERSION)
        self.assertEqual((reply.tool_use_id, reply.usage), ("t9", {"input_tokens": 5}))

    def test_missing_key_is_reported(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(llm.ApiError):
                llm.AnthropicClient(api_key=None).complete([], [])

    def test_load_env_does_not_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("# c\nZB_TEST_A=1\nZB_TEST_B='two'\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"ZB_TEST_A": "keep"}, clear=False):
                llm.load_env(Path(tmp))
                self.assertEqual((os.environ["ZB_TEST_A"], os.environ["ZB_TEST_B"]), ("keep", "two"))
            os.environ.pop("ZB_TEST_B", None)


if __name__ == "__main__":
    unittest.main()


class MemoryTest(unittest.TestCase):
    def test_memory_is_added_only_when_it_still_applies(self):
        from zinro_bot.engine import make_memory, memory_text

        table = parse_table(LOG)
        client = llm.ScriptedClient([{**good(), "read": {"aim": "アリスを詰める", "players": {"アリス": "基準が曖昧"}, "pending": ["#4 への返事"], "swing": "カレンが傾く", "aim2": ""}, "vote": "アリス"}])
        result = respond(client, CTX, table)
        memory = make_memory(table, result.turn)
        text = memory_text(memory, table)
        self.assertIn("狙い: アリスを詰める", text)
        self.assertIn("投票先の見込み: アリス", text)
        self.assertIn("前回の自分のメモ", user_message(table, memory=memory))
        self.assertEqual(memory_text({**memory, "me": "別人"}, table), "")
        self.assertEqual(memory_text({**memory, "posts_seen": 99}, table), "")
        self.assertEqual(memory_text(None, table), "")
