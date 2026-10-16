import unittest

from zinro_bot.validate import build_turn, check_text, clean_reply_to, normalize_text

MOVES = {"rebut", "probe", "tally"}
EXAMPLES = ["それは違うと思う。理由はこの二つの発言の食い違いにある。"]


def turn(data, **kw):
    args = dict(me="ボブ", players=["ボブ", "アリス", "カレン"], last_seq=5, known_moves=MOVES, examples=EXAMPLES)
    args.update(kw)
    return build_turn(data, **args)


def post(text, reply_to=(1,), moves=("rebut",)):
    return {"text": text, "reply_to": list(reply_to), "moves": list(moves)}


class CheckTextTest(unittest.TestCase):
    def problems(self, text):
        return check_text(text, EXAMPLES)[0]

    def test_plain_text_passes(self):
        self.assertEqual(self.problems("それは根拠が弱いと思う。アリスはどこでそう決めたの？"), [])

    def test_explanatory_and_ai_words_are_rejected(self):
        self.assertTrue(any("つまり" in p for p in self.problems("つまり、そういうこと。")))
        self.assertTrue(any("ご指摘" in p for p in self.problems("ご指摘の通りだと思う。")))

    def test_kansai_endings_are_rejected_but_standard_forms_pass(self):
        self.assertTrue(self.problems("それはおかしいやろ。"))
        self.assertTrue(self.problems("ほんまにそう思うの？"))
        self.assertEqual(self.problems("議論をやろう。今やってる話を続けよう。"), [])

    def test_list_markup_and_internal_numbers_are_rejected(self):
        self.assertTrue(self.problems("- 一つ目\n- 二つ目"))
        self.assertTrue(self.problems("**重要**です"))
        self.assertTrue(self.problems("#3 の発言について"))

    def test_length_and_lines(self):
        self.assertTrue(self.problems("あ" * 241))
        self.assertEqual(check_text("あ" * 210, EXAMPLES)[0], [])
        self.assertTrue(any("長め" in w for w in check_text("あ" * 210, EXAMPLES)[1]))
        self.assertTrue(self.problems("\n".join(["行"] * 6)))

    def test_claiming_to_be_wolf_and_copying_examples_are_rejected(self):
        self.assertTrue(self.problems("自分は人狼です。"))
        self.assertTrue(any("写し" in p for p in self.problems("それは違うと思う。理由はこの二つの発言の食い違いにある。だから吊る。")))

    def test_ai_mentions_only_warn(self):
        problems, warnings = check_text("AIかと聞かれたら、そうだよ。", EXAMPLES)
        self.assertEqual(problems, [])
        self.assertTrue(warnings)


class NormalizeTest(unittest.TestCase):
    def test_own_name_prefix_and_blank_lines_are_removed(self):
        self.assertEqual(normalize_text("ボブ: こんにちは\n\n\n\nどうも", "ボブ"), "こんにちは\n\nどうも")

    def test_reply_to_is_sorted_deduplicated_and_limited(self):
        self.assertEqual(clean_reply_to([3, "#2", 9, 2], 5), ([2, 3], ["存在しない発言番号を返信先から除いた"]))
        valid, warnings = clean_reply_to([1, 2, 3, 4, 5], 5)
        self.assertEqual(valid, [2, 3, 4, 5])
        self.assertTrue(warnings)


class BuildTurnTest(unittest.TestCase):
    def test_valid_turn(self):
        t = turn({"read": {"aim": "詰める"}, "posts": [post("根拠を聞きたい。", moves=["probe", "unknown"])], "vote": "アリス", "silence": ""})
        self.assertEqual([p.text for p in t.posts], ["根拠を聞きたい。"])
        self.assertEqual(t.posts[0].moves, ["probe"])
        self.assertEqual((t.vote, t.problems), ("アリス", []))

    def test_bad_posts_are_dropped_with_reasons(self):
        t = turn({"read": {}, "posts": [post("つまり違う。"), post("根拠は？")], "vote": None, "silence": ""})
        self.assertEqual([p.text for p in t.posts], ["根拠は？"])
        self.assertTrue(any("投稿1" in p and "つまり" in p for p in t.problems))

    def test_invalid_vote_is_ignored_and_extra_posts_are_cut(self):
        t = turn({"read": {}, "posts": [post(f"発言{i}") for i in range(6)], "vote": "ボブ", "silence": ""})
        self.assertEqual(len(t.posts), 4)
        self.assertIsNone(t.vote)
        self.assertTrue(t.warnings)

    def test_silence_is_kept(self):
        t = turn({"read": {}, "posts": [], "vote": None, "silence": "新しい材料がない"})
        self.assertEqual((t.posts, t.silence), ([], "新しい材料がない"))


if __name__ == "__main__":
    unittest.main()
