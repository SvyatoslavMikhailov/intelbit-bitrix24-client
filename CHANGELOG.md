# Changelog

## [0.3.0] — 2026-10-02

### Добавлено

- `Bitrix24Client.call_v3(method, payload)`: REST v3 — POST JSON на
  `/rest/api/{uid}/{token}/{method}` (путь выводится из URL входящего вебхука).
  Ошибка v3 `{"error": {"code", "message", "validation"}}` → `Bitrix24Error` с
  атрибутом `validation` и перечнем полей в тексте; старая строковая форма ошибки по
  v3-пути тоже приводится. Общий rate limiter, повтор `QUERY_LIMIT`, TLS и `_transport`
  — как у `call`. Нужен для чата задачи (`tasks.task.chat.message.send`).
- Модуль `bbcode`: `escape()` (описания задач, форум: `&#91;`/`&#93;`), `escape_chat()`
  (чат задачи и `im.message.add`: ZWSP в скобке тега — сущности портал декодирует),
  `convert()` — обратная операция.
- `Bitrix24Error.validation` (для v2 — пустой список).

## [0.2.0] — 2026-10-02

### Добавлено

- Параметры конструктора `verify: bool | str = True` и `ca_bundle: str | None = None`:
  проверка TLS-сертификата портала Bitrix24 с корпоративным CA (непустой `ca_bundle`
  → `ssl.create_default_context(cafile=...)`, важнее `verify`; нет файла → `ValueError`).
  Пробрасываются в каждый `httpx.AsyncClient`.
- Тесты TLS с самоподписанным сертификатом (`trustme`, локальный HTTPS-сервер).

## [0.1.0]

- Первый выпуск: клиент REST Bitrix24 (входящий вебхук), пагинация, батч, rate limit.
