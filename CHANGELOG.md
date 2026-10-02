# Changelog

## [0.2.0] — 2026-10-02

### Добавлено

- Параметры конструктора `verify: bool | str = True` и `ca_bundle: str | None = None`:
  проверка TLS-сертификата портала Bitrix24 с корпоративным CA (непустой `ca_bundle`
  → `ssl.create_default_context(cafile=...)`, важнее `verify`; нет файла → `ValueError`).
  Пробрасываются в каждый `httpx.AsyncClient`.
- Тесты TLS с самоподписанным сертификатом (`trustme`, локальный HTTPS-сервер).

## [0.1.0]

- Первый выпуск: клиент REST Bitrix24 (входящий вебхук), пагинация, батч, rate limit.
