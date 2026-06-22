# intelbit-bitrix24-client

Async-клиент **Bitrix24 REST** (входящий вебхук коробки) — общая Apache-библиотека для:

- Интелбит Bitrix24 **MCP** (проект 4-23);
- **Река-коннектора** Bitrix24 (`intelbit-river-connector-bitrix24`, проект 4-17 Фаза 5).

Только чистый REST-клиент: вызовы, батч, пагинация, обработка ошибок, rate-limit. Без Dadata, лидогенерации и FastAPI-обвязки.

## Установка

```bash
uv sync --extra dev
```

## Использование

```python
from intelbit_bitrix24_client import Bitrix24Client

client = Bitrix24Client("https://portal.bitrix24.ru/rest/1/xxxxxxxx/", rps=2.0)

# Одиночный вызов — возвращает конверт {result, total?, next?}
env = await client.call("crm.company.get", {"id": 7})
company = env["result"]

# Пагинация (страница 50, через start/next/total)
async for row in client.list_all("crm.company.list", {"select": ["ID", "TITLE"]}):
    ...

# Новые catalog.* оборачивают список в объект — укажи result_key
async for product in client.list_all("catalog.product.list", {"filter": {"iblockId": 14}},
                                     result_key="products"):
    ...

# Батч до 50 команд
out = await client.call_batch({
    "company": ("crm.company.get", {"id": 7}),
    "deal": ("crm.deal.get", {"id": 42}),
})
```

## Контракт

- Авторизация встроена в URL входящего вебхука: `https://<portal>/rest/<user_id>/<token>/`.
- Соединения **не держатся** между вызовами (ADR-006): `httpx.AsyncClient` открывается и
  закрывается на каждый запрос.
- На `QUERY_LIMIT_EXCEEDED` — экспоненциальный backoff и повтор через rate-limiter.

## Разработка

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

## Происхождение

Код извлечён из `bitrix24-mcp` (проект 4-23). Интелбит — автор кода и держатель CLA;
релицензирование под Apache 2.0 правомерно.
