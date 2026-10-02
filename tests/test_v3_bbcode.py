"""Тесты REST v3 (call_v3) и экранирования BBCode (bbcode)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from intelbit_bitrix24_client import Bitrix24Client, Bitrix24Error, QueryLimitExceeded, bbcode

BASE = "https://portal.example/rest/1/tok42/"
V3 = "https://portal.example/rest/api/1/tok42/"


def _client() -> Bitrix24Client:
    return Bitrix24Client(BASE, rps=1000.0, retry_backoff=0.001)


@respx.mock
async def test_call_v3_posts_json_to_api_path() -> None:
    route = respx.post(f"{V3}tasks.task.chat.message.send").mock(
        return_value=httpx.Response(200, json={"result": {"result": True}})
    )
    payload = {"fields": {"taskId": 5, "text": "Привет"}}
    result = await _client().call_v3("tasks.task.chat.message.send", payload)
    assert result == {"result": {"result": True}}
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("application/json")
    assert json.loads(request.content) == payload


@respx.mock
async def test_call_v3_error_with_validation() -> None:
    respx.post(f"{V3}tasks.task.chat.message.send").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "code": "BITRIX_REST_V3_EXCEPTION_VALIDATION_REQUESTVALIDATIONEXCEPTION",
                    "message": "Ошибка валидации",
                    "validation": [{"field": "taskId", "message": "обязательно"}],
                }
            },
        )
    )
    with pytest.raises(Bitrix24Error) as exc_info:
        await _client().call_v3("tasks.task.chat.message.send", {"fields": {}})
    exc = exc_info.value
    assert exc.validation == [{"field": "taskId", "message": "обязательно"}]
    assert "taskId: обязательно" in str(exc)
    assert exc.status_code == 400


@respx.mock
async def test_call_v3_legacy_string_error() -> None:
    respx.post(f"{V3}x.method").mock(
        return_value=httpx.Response(
            404, json={"error": "ERROR_METHOD_NOT_FOUND", "error_description": "нет"}
        )
    )
    with pytest.raises(Bitrix24Error) as exc_info:
        await _client().call_v3("x.method", {})
    assert exc_info.value.code == "ERROR_METHOD_NOT_FOUND"
    assert exc_info.value.validation == []


@respx.mock
async def test_call_v3_query_limit_retried() -> None:
    route = respx.post(f"{V3}x.method").mock(
        side_effect=[
            httpx.Response(503, json={"error": {"code": "QUERY_LIMIT_EXCEEDED", "message": "x"}}),
            httpx.Response(200, json={"result": {"ok": True}}),
        ]
    )
    assert await _client().call_v3("x.method", {}) == {"result": {"ok": True}}
    assert route.call_count == 2


@respx.mock
async def test_call_v3_query_limit_exhausted() -> None:
    respx.post(f"{V3}x.method").mock(
        return_value=httpx.Response(
            503, json={"error": {"code": "QUERY_LIMIT_EXCEEDED", "message": "x"}}
        )
    )
    client = Bitrix24Client(BASE, rps=1000.0, retry_backoff=0.001, max_retries=1)
    with pytest.raises(QueryLimitExceeded):
        await client.call_v3("x.method", {})


async def test_v3_base_requires_rest_segment() -> None:
    # Конструктор не падает (как и у v2) — ошибка только при v3-вызове.
    client = Bitrix24Client("https://portal.example/hook/1/tok/")
    with pytest.raises(ValueError, match="/rest/"):
        await client.call_v3("x.method", {})


class TestBbcode:
    def test_escape_description(self) -> None:
        assert bbcode.escape("[b]x[/b] arr[0]") == "&#91;b&#93;x&#91;/b&#93; arr&#91;0&#93;"
        assert bbcode.escape(None) == ""

    def test_escape_chat_breaks_tags_keeps_indexes(self) -> None:
        text = "[b]важно[/b] [URL=http://x]ссылка[/URL] [*] arr[0] [DISK FILE ID=n30419]"
        out = bbcode.escape_chat(text)
        assert f"[{bbcode.ZWSP}b]" in out
        assert f"[{bbcode.ZWSP}/b]" in out
        assert f"[{bbcode.ZWSP}URL=http://x]" in out
        assert f"[{bbcode.ZWSP}*]" in out
        assert f"[{bbcode.ZWSP}DISK FILE ID=n30419]" in out
        assert "arr[0]" in out

    def test_round_trip(self) -> None:
        text = "[b]важно[/b] arr[0] [*] пункт"
        assert bbcode.convert(bbcode.escape_chat(text)) == text
        assert bbcode.convert(bbcode.escape(text)) == text
