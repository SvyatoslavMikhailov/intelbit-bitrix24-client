"""Исключения клиента Bitrix24 REST."""

from __future__ import annotations

from typing import Any


class Bitrix24Error(RuntimeError):
    """Bitrix24 вернул ошибку (поле `error` в конверте либо транспортный сбой).

    Для REST v3 в `.validation` лежит список полей, не прошедших проверку
    (`[{"field": …, "message": …}]`); у v2 он пуст.
    """

    def __init__(
        self,
        code: str,
        description: str,
        status_code: int | None = None,
        validation: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code
        self.description = description
        self.status_code = status_code
        self.validation = validation or []
        super().__init__(f"[{code}] {description}")


class QueryLimitExceeded(Bitrix24Error):  # noqa: N818  # имя задано контрактом промпта 4-17-17
    """`QUERY_LIMIT_EXCEEDED` — лимит запросов исчерпан и backoff не помог."""
