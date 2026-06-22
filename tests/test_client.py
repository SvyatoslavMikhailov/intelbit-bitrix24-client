"""Тесты Bitrix24Client на respx: call / batch / list_all / конверт ошибки / backoff."""

from __future__ import annotations

import httpx
import pytest
import respx

from intelbit_bitrix24_client import (
    Bitrix24Client,
    Bitrix24Error,
    QueryLimitExceeded,
    TokenBucket,
    flatten,
)

BASE = "https://portal.example/rest/1/tok42/"


def _client(**kw: object) -> Bitrix24Client:
    # rps высокий + backoff крошечный — тесты не упираются в сон.
    return Bitrix24Client(BASE, rps=1000.0, retry_backoff=0.001, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# flatten (unit)
# --------------------------------------------------------------------------- #


def test_flatten_php_style() -> None:
    out = flatten({"FILTER": {">OPPORTUNITY": 100}, "SELECT": ["ID", "TITLE"]})
    assert out["FILTER[>OPPORTUNITY]"] == "100"
    assert out["SELECT[0]"] == "ID"
    assert out["SELECT[1]"] == "TITLE"


def test_flatten_bool() -> None:
    assert flatten({"ACTIVE": True}) == {"ACTIVE": "1"}
    assert flatten({"ACTIVE": False}) == {"ACTIVE": "0"}


# --------------------------------------------------------------------------- #
# call
# --------------------------------------------------------------------------- #


@respx.mock
async def test_call_returns_envelope() -> None:
    respx.post(f"{BASE}crm.company.get").mock(
        return_value=httpx.Response(200, json={"result": {"ID": "7", "TITLE": "ООО Ромашка"}})
    )
    env = await _client().call("crm.company.get", {"id": 7})
    assert env["result"]["TITLE"] == "ООО Ромашка"


@respx.mock
async def test_call_exposes_total_and_next() -> None:
    respx.post(f"{BASE}crm.deal.list").mock(
        return_value=httpx.Response(200, json={"result": [{"ID": "1"}], "total": 120, "next": 50})
    )
    env = await _client().call("crm.deal.list")
    assert env["total"] == 120
    assert env["next"] == 50


@respx.mock
async def test_call_error_raises() -> None:
    respx.post(f"{BASE}crm.company.get").mock(
        return_value=httpx.Response(
            400, json={"error": "INVALID_REQUEST", "error_description": "нет id"}
        )
    )
    with pytest.raises(Bitrix24Error) as exc:
        await _client().call("crm.company.get")
    assert exc.value.code == "INVALID_REQUEST"
    assert exc.value.status_code == 400


@respx.mock
async def test_call_bad_response_raises() -> None:
    respx.post(f"{BASE}crm.company.get").mock(
        return_value=httpx.Response(200, text="<html>500</html>")
    )
    with pytest.raises(Bitrix24Error) as exc:
        await _client().call("crm.company.get")
    assert exc.value.code == "bad_response"


@respx.mock
async def test_query_limit_retries_then_succeeds() -> None:
    route = respx.post(f"{BASE}crm.company.list").mock(
        side_effect=[
            httpx.Response(
                200, json={"error": "QUERY_LIMIT_EXCEEDED", "error_description": "wait"}
            ),
            httpx.Response(200, json={"result": [{"ID": "1"}]}),
        ]
    )
    env = await _client().call("crm.company.list")
    assert env["result"] == [{"ID": "1"}]
    assert route.call_count == 2


@respx.mock
async def test_query_limit_exhausted_raises() -> None:
    respx.post(f"{BASE}crm.company.list").mock(
        return_value=httpx.Response(
            200, json={"error": "QUERY_LIMIT_EXCEEDED", "error_description": "wait"}
        )
    )
    with pytest.raises(QueryLimitExceeded):
        await _client(max_retries=2).call("crm.company.list")


# --------------------------------------------------------------------------- #
# call_batch
# --------------------------------------------------------------------------- #


@respx.mock
async def test_call_batch_parses_result_and_error() -> None:
    respx.post(f"{BASE}batch").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "result": {"a": {"ID": "1"}},
                    "result_error": {"b": "ACCESS_DENIED"},
                    "result_total": {"a": 1},
                    "result_next": {},
                }
            },
        )
    )
    out = await _client().call_batch(
        {"a": ("crm.company.get", {"id": 1}), "b": ("crm.deal.get", {"id": 2})}
    )
    assert out["result"]["a"]["ID"] == "1"
    assert out["result_error"]["b"] == "ACCESS_DENIED"


async def test_call_batch_over_limit_raises() -> None:
    cmds = {f"c{i}": ("crm.company.get", {"id": i}) for i in range(51)}
    with pytest.raises(ValueError, match="50"):
        await _client().call_batch(cmds)


@respx.mock
async def test_call_batch_encodes_commands() -> None:
    route = respx.post(f"{BASE}batch").mock(
        return_value=httpx.Response(200, json={"result": {"result": {}}})
    )
    await _client().call_batch({"x": ("crm.company.get", {"id": 7})})
    sent = route.calls.last.request.content.decode()
    # cmd[x]=crm.company.get?id=7 — '?' и '=' внутри значения form-поля экранированы.
    assert "cmd%5Bx%5D=crm.company.get%3Fid%3D7" in sent


# --------------------------------------------------------------------------- #
# list_all
# --------------------------------------------------------------------------- #


@respx.mock
async def test_list_all_paginates_via_next() -> None:
    respx.post(f"{BASE}crm.company.list").mock(
        side_effect=[
            httpx.Response(200, json={"result": [{"ID": "1"}, {"ID": "2"}], "total": 3, "next": 2}),
            httpx.Response(200, json={"result": [{"ID": "3"}], "total": 3}),
        ]
    )
    rows = [r async for r in _client().list_all("crm.company.list")]
    assert [r["ID"] for r in rows] == ["1", "2", "3"]


@respx.mock
async def test_list_all_stops_without_next() -> None:
    route = respx.post(f"{BASE}crm.deal.list").mock(
        return_value=httpx.Response(200, json={"result": [{"ID": "1"}], "total": 1})
    )
    rows = [r async for r in _client().list_all("crm.deal.list")]
    assert len(rows) == 1
    assert route.call_count == 1


@respx.mock
async def test_list_all_catalog_result_key() -> None:
    respx.post(f"{BASE}catalog.product.list").mock(
        side_effect=[
            httpx.Response(
                200, json={"result": {"products": [{"id": 1}, {"id": 2}]}, "total": 3, "next": 2}
            ),
            httpx.Response(200, json={"result": {"products": [{"id": 3}]}, "total": 3}),
        ]
    )
    rows = [r async for r in _client().list_all("catalog.product.list", result_key="products")]
    assert [r["id"] for r in rows] == [1, 2, 3]


# --------------------------------------------------------------------------- #
# rate limiter (unit)
# --------------------------------------------------------------------------- #


def test_token_bucket_drains_and_blocks() -> None:
    clock = [0.0]
    bucket = TokenBucket(rps=2.0, time_func=lambda: clock[0])
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False  # ёмкость 2 исчерпана
    assert bucket.time_until_available() == pytest.approx(0.5)
    clock[0] = 1.0  # +1s -> +2 токена
    assert bucket.try_acquire() is True
