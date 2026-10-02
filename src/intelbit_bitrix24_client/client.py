"""Bitrix24Client — async REST-клиент входящего вебхука коробки Bitrix24.

Извлечён из проекта 4-23 (intelbit `bitrix24-mcp`) и приведён к контракту ADR-006:
соединения не держим между вызовами — `httpx.AsyncClient` открывается и
закрывается на каждый запрос (acquire-on-call). In-memory state сверх пула нет.
"""

from __future__ import annotations

import os
import ssl
from collections.abc import AsyncIterator
from typing import Any

import httpx

from intelbit_bitrix24_client.errors import Bitrix24Error, QueryLimitExceeded
from intelbit_bitrix24_client.ratelimit import TokenBucket

# Bitrix24 ограничивает батч 50 командами на один вызов `batch`.
BATCH_MAX = 50
# Размер страницы list-методов Bitrix24 фиксирован платформой.
PAGE_SIZE = 50


def flatten(params: Any, prefix: str = "") -> dict[str, str]:
    """Развернуть вложенные dict/list в PHP-style form-параметры Bitrix24.

    Примеры::

        {"FILTER": {">OPPORTUNITY": 100}} -> {"FILTER[>OPPORTUNITY]": "100"}
        {"SELECT": ["ID", "TITLE"]}       -> {"SELECT[0]": "ID", "SELECT[1]": "TITLE"}
    """
    out: dict[str, str] = {}
    if params is None:
        return out
    if isinstance(params, dict):
        for key, value in params.items():
            sub = f"{prefix}[{key}]" if prefix else str(key)
            out.update(flatten(value, sub))
    elif isinstance(params, list | tuple):
        for idx, value in enumerate(params):
            out.update(flatten(value, f"{prefix}[{idx}]"))
    elif isinstance(params, bool):
        out[prefix] = "1" if params else "0"
    else:
        out[prefix] = str(params)
    return out


def _tls_verify(verify: bool | str, ca_bundle: str | None) -> bool | ssl.SSLContext:
    """Параметр `verify` для httpx: корпоративный CA → SSLContext, иначе bool/путь.

    Путь строкой httpx объявил устаревшим — CA превращается в SSLContext.

    Raises:
        ValueError: файл CA не найден.
    """
    cafile = ca_bundle or (verify if isinstance(verify, str) else None)
    if cafile:
        if not os.path.isfile(cafile):
            raise ValueError(f"Bitrix24: файл корпоративного CA не найден: {cafile}")
        return ssl.create_default_context(cafile=cafile)
    return bool(verify)


class Bitrix24Client:
    """Async-клиент REST Bitrix24 для входящего вебхука коробки.

    Авторизация встроена в URL входящего вебхука:
    ``https://<portal>/rest/<user_id>/<token>/``.
    """

    def __init__(
        self,
        webhook_base_url: str,
        *,
        rps: float = 2.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
        verify: bool | str = True,
        ca_bundle: str | None = None,
        _transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Args:
        verify: Проверка TLS-сертификата портала (False — отключить) или путь к CA.
        ca_bundle: Путь к корпоративному CA; непустой — важнее `verify`.
        """
        if not webhook_base_url.endswith("/"):
            webhook_base_url += "/"
        self._base_url = webhook_base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._bucket = TokenBucket(rps)
        # _transport — для contract-тестов через httpx.ASGITransport (FastAPI-мок).
        self._transport = _transport
        self._verify = _tls_verify(verify, ca_bundle)

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Один REST-вызов. Возвращает разобранный конверт ``{result, total?, next?}``.

        На ``QUERY_LIMIT_EXCEEDED`` — backoff и повтор через rate-limiter.
        """
        return await self._request(method, params or {})

    async def call_v3(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Вызов метода REST **v3**: POST JSON на `/rest/api/{uid}/{token}/{method}`.

        Версия выбирается явно: v3-метод по пути v2 отвечает `ERROR_METHOD_NOT_FOUND`
        и наоборот (так на 4-23-11 `tasks.task.chat.message.send` был ошибочно сочтён
        отсутствующим). Квота портала общая — тот же rate limiter, что у `call`;
        `QUERY_LIMIT` повторяется с backoff. Возвращает полный ответ (`result` и т.д.).

        Raises:
            Bitrix24Error: ошибка v3 (`.validation` — непрошедшие поля) или транспорт.
        """
        # v3-база вычисляется при вызове: конструктор не должен падать на неполном
        # конфиге (коннектор без URL сообщает об этом через health, а не исключением).
        url = f"{_v3_base(self._base_url)}{method}"
        for attempt in range(self._max_retries + 1):
            await self._bucket.acquire()
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport, verify=self._verify
            ) as client:
                try:
                    resp = await client.post(url, json=payload or {})
                except httpx.HTTPError as exc:
                    raise Bitrix24Error("transport_error", str(exc)) from exc

            data = _parse_json(resp)
            error = data.get("error")
            if error:
                exc_v3 = _v3_error(error, resp.status_code)
                if _is_query_limit(exc_v3.code, resp.status_code):
                    if attempt < self._max_retries:
                        await _backoff(self._retry_backoff, attempt)
                        continue
                    raise QueryLimitExceeded(exc_v3.code, exc_v3.description, resp.status_code)
                raise exc_v3
            return data

        raise QueryLimitExceeded(
            "QUERY_LIMIT_EXCEEDED", f"лимит не освободился за {self._max_retries} повторов"
        )

    async def call_batch(
        self,
        commands: dict[str, tuple[str, dict[str, Any]]],
        *,
        halt: bool = False,
    ) -> dict[str, Any]:
        """Батч до 50 команд через метод ``batch``.

        ``commands`` — отображение имя → (метод, параметры). Возвращает
        ``{result, result_error, result_total, result_next}``.
        """
        if len(commands) > BATCH_MAX:
            raise ValueError(
                f"Батч Bitrix24 ограничен {BATCH_MAX} командами, передано {len(commands)}"
            )
        cmd: dict[str, str] = {}
        for name, (method, params) in commands.items():
            query = "&".join(f"{k}={v}" for k, v in flatten(params).items())
            cmd[name] = f"{method}?{query}" if query else method

        envelope = await self._request("batch", {"halt": 1 if halt else 0, "cmd": cmd})
        result = envelope.get("result", {})
        if not isinstance(result, dict):
            result = {}
        return {
            "result": result.get("result", {}),
            "result_error": result.get("result_error", {}),
            "result_total": result.get("result_total", {}),
            "result_next": result.get("result_next", {}),
        }

    async def list_all(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        result_key: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Пагинация list-метода через ``start``/``next``/``total`` (страница 50).

        Большинство CRM-методов кладут список прямо в ``result``. Новые
        ``catalog.*`` оборачивают его в объект — тогда передай ``result_key``
        (например ``"products"`` для ``catalog.product.list``).
        """
        params = dict(params or {})
        start = params.pop("start", 0)
        while True:
            envelope = await self._request(method, {**params, "start": start})
            result = envelope.get("result", [])
            if isinstance(result, dict) and result_key is not None:
                rows = result.get(result_key, [])
            elif isinstance(result, list):
                rows = result
            else:
                rows = [result] if result else []
            for row in rows:
                yield row
            if "next" in envelope and envelope["next"] is not None:
                start = envelope["next"]
            else:
                break

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{method}"
        form = flatten(params)
        for attempt in range(self._max_retries + 1):
            await self._bucket.acquire()
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport, verify=self._verify
            ) as client:
                try:
                    resp = await client.post(url, data=form)
                except httpx.HTTPError as exc:
                    raise Bitrix24Error("transport_error", str(exc)) from exc

            payload = _parse_json(resp)
            error = payload.get("error")
            if error:
                description = payload.get("error_description", "")
                if error == "QUERY_LIMIT_EXCEEDED":
                    if attempt < self._max_retries:
                        await _backoff(self._retry_backoff, attempt)
                        continue
                    raise QueryLimitExceeded(error, description, resp.status_code)
                raise Bitrix24Error(error, description, resp.status_code)
            return payload

        raise QueryLimitExceeded(
            "QUERY_LIMIT_EXCEEDED", f"лимит не освободился за {self._max_retries} повторов"
        )


def _v3_base(webhook_url: str) -> str:
    """URL вебхука v2 → база v3: `/rest/{uid}/{token}/` → `/rest/api/{uid}/{token}/`."""
    head, sep, tail = webhook_url.partition("/rest/")
    if not sep or not tail:
        raise ValueError("Не похоже на URL входящего вебхука Bitrix24 (нет сегмента /rest/)")
    if tail.startswith("api/"):
        return webhook_url
    return f"{head}/rest/api/{tail}"


def _v3_error(raw: Any, status_code: int | None) -> Bitrix24Error:
    """Ошибка v3 `{"code", "message", "validation": [{"field", "message"}]}` → Bitrix24Error.

    Портал изредка отвечает по v3-пути ошибкой в старой форме (строка) — её тоже
    приводим, чтобы наружу не уходил сырой JSON.
    """
    if not isinstance(raw, dict):
        return Bitrix24Error(str(raw) or "unknown_error", "", status_code)
    code = str(raw.get("code") or "unknown_error")
    message = str(raw.get("message") or "")
    fields: list[dict[str, Any]] = []
    validation = raw.get("validation")
    if isinstance(validation, list):
        for item in validation:
            if isinstance(item, dict):
                fields.append({"field": item.get("field"), "message": item.get("message")})
    if fields:
        detail = "; ".join(
            f"{f['field']}: {f['message']}" if f["field"] else str(f["message"]) for f in fields
        )
        message = f"{message} — {detail}" if message else detail
    return Bitrix24Error(code, message, status_code, validation=fields)


def _is_query_limit(code: str, status_code: int | None) -> bool:
    """Признак «лимит запросов исчерпан» для v3 (код у v3 длиннее, чем у v2)."""
    return "QUERY_LIMIT" in code.upper() or status_code == 503


def _parse_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data: Any = resp.json()
    except ValueError as exc:
        raise Bitrix24Error(
            "bad_response",
            f"не-JSON ответ (status={resp.status_code}): {resp.text[:200]}",
            status_code=resp.status_code,
        ) from exc
    if not isinstance(data, dict):
        raise Bitrix24Error("bad_response", "Bitrix24 вернул не-JSON-объект", resp.status_code)
    return data


async def _backoff(base: float, attempt: int) -> None:
    import asyncio

    await asyncio.sleep(base * (2**attempt))
