"""Anthropic の Messages API を、標準ライブラリだけで呼ぶ薄いクライアントと、テスト用の台本クライアント。

出力は tool use(submit_turn)で JSON を受ける。tool の入力の並びは read → posts → vote なので、
モデルは読みを先に書いてから発言を書く。キーは環境変数 ANTHROPIC_API_KEY(または、リポジトリ直下の .env)。

tool の強制(tool_choice の tool / any)と、思考の token 数の指定(budget_tokens)は、claude-opus-5-5 などの
新しいモデルでは 400 になる。tool は auto で呼ばせ(呼ぶ指示はユーザー側のメッセージに入れる)、
考える量は effort で変える。tool を呼ばずに文章で返したときは、文章の中の JSON を読む。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5-5"
API_VERSION = "2023-06-01"
TOOL_NAME = "submit_turn"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

TOOL = {
    "name": TOOL_NAME,
    "description": "このターンの読みと、次にチャットへ貼る発言(0〜4件)を提出する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "read": {
                "type": "object",
                "properties": {
                    "players": {"type": "object", "additionalProperties": {"type": "string"}},
                    "pending": {"type": "array", "items": {"type": "string"}},
                    "swing": {"type": "string"},
                    "aim": {"type": "string"},
                },
                "required": ["players", "pending", "swing", "aim"],
            },
            "posts": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "reply_to": {"type": "array", "items": {"type": "integer"}, "maxItems": 4},
                        "moves": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                        "text": {"type": "string"},
                    },
                    "required": ["reply_to", "moves", "text"],
                },
            },
            "vote": {"type": ["string", "null"]},
            "silence": {"type": "string"},
        },
        "required": ["read", "posts", "vote", "silence"],
    },
}


class ApiError(RuntimeError):
    pass


@dataclass
class Reply:
    data: dict
    usage: dict = field(default_factory=dict)
    content: list = field(default_factory=list)  # 次の呼び出しに、assistant の発言として戻す
    tool_use_id: str | None = None


def load_env(root: Path) -> None:
    """リポジトリ直下の .env(KEY=VALUE の行)を、未設定の環境変数に読み込む。.env は git に載せない。"""
    path = Path(root) / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def parse_json_text(text: str) -> dict:
    """tool を使わずに、文章の中に JSON が入って返ってきたとき用。最初の { から最後の } まで。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ApiError("応答に JSON が見つからない")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ApiError(f"応答の JSON を読めない: {exc}") from exc


def extract(content: list) -> tuple[dict, str | None]:
    """応答の content から、(提出された JSON, tool_use の id)。"""
    for block in content:
        if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
            return block.get("input") or {}, block.get("id")
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    return parse_json_text(text), None


class AnthropicClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 8192,  # 思考の token も、ここに数えられる
        timeout: int = 240,
        retries: int = 3,
        effort: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ZINRO_BOT_MODEL") or DEFAULT_MODEL
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = retries
        self.effort = effort

    def body(self, system: list[dict], messages: list[dict]) -> dict:
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
            "tools": [TOOL],
            "tool_choice": {"type": "auto"},  # 強制(tool / any)は、新しいモデルでは 400。呼ばせるのは、ユーザー側のメッセージの指示で行う
        }
        if self.effort:
            body["output_config"] = {"effort": self.effort}  # 考える量(low〜max)。Opus 5.5 は、思考を切れない。省略時はモデルの既定
        return body

    def complete(self, system: list[dict], messages: list[dict]) -> Reply:
        if not self.api_key:
            raise ApiError("ANTHROPIC_API_KEY が設定されていません(環境変数、または .env に書く)")
        request = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=json.dumps(self.body(system, messages), ensure_ascii=False).encode("utf-8"),
            headers={"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"},
            method="POST",
        )
        delay = 2.0
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                if exc.code in RETRY_STATUS and attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ApiError(f"API エラー {exc.code}: {detail[:500]}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ApiError(f"API に接続できない: {exc}") from exc
        stop = payload.get("stop_reason")
        if stop == "refusal":
            raise ApiError("モデルが応答を断った(stop_reason: refusal)")
        if stop == "max_tokens":
            raise ApiError(f"出力が max_tokens({self.max_tokens})で切れた。--effort を下げると、考える分が減る")
        content = payload.get("content", [])
        data, tool_id = extract(content)
        return Reply(data, payload.get("usage", {}), content, tool_id)


class ScriptedClient:
    """台本どおりに返すクライアント(テストと、--fake の動作確認用)。呼び出しの記録は calls に残る。"""

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def complete(self, system: list[dict], messages: list[dict]) -> Reply:
        self.calls.append((system, messages))
        if not self.replies:
            raise ApiError("台本が尽きた")
        data = self.replies.pop(0)
        block = {"type": "tool_use", "id": f"fake_{len(self.calls)}", "name": TOOL_NAME, "input": data}
        return Reply(data, {}, [block], block["id"])
