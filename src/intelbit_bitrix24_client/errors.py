"""Исключения клиента Bitrix24 REST."""

from __future__ import annotations


class Bitrix24Error(RuntimeError):
    """Bitrix24 вернул ошибку (поле `error` в конверте либо транспортный сбой)."""

    def __init__(self, code: str, description: str, status_code: int | None = None) -> None:
        self.code = code
        self.description = description
        self.status_code = status_code
        super().__init__(f"[{code}] {description}")


class QueryLimitExceeded(Bitrix24Error):  # noqa: N818  # имя задано контрактом промпта 4-17-17
    """`QUERY_LIMIT_EXCEEDED` — лимит запросов исчерпан и backoff не помог."""
