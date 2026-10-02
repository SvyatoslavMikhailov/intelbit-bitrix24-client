"""Экранирование BBCode для записи в Bitrix24 (описания задач, форум, чат).

Два режима, потому что хранилища ведут себя по-разному (проверено на живом портале,
4-23-13, 26.07.2026):

- `escape()` — описания задач и форум (`task.comment.add`): скобки → HTML-сущности
  `&#91;`/`&#93;`, портал показывает их как `[`/`]`;
- `escape_chat()` — чат задачи и `im.message.add`: сущности портал декодирует при
  записи, поэтому в скобку тега вставляется символ нулевой ширины (ZWSP) — человек
  видит текст дословно, парсер тега не узнаёт.

`convert()` — обратная операция для чтения: снимает сущности и ZWSP (round-trip точный).
"""

from __future__ import annotations

import re

# Невидимый разделитель (zero-width space).
ZWSP = "​"

# Тег вида [tag], [/tag], [tag=value]: имя — латиница/цифры, поэтому `[файл: …]`,
# markdown-ссылки и индексы `arr[0]` не задеваются.
_ANY_TAG_RE = re.compile(r"\[/?[A-Za-z][A-Za-z0-9]*(?:=[^\]\s]*)?\]")
# Маркер списка [*] — единственный тег, который не ловит _ANY_TAG_RE.
_LIST_ITEM_RE = re.compile(r"\[\*\]")
# Маркер вложения [DISK FILE ID=n30419] (с пробелами внутри).
_DISK_RE = re.compile(r"\[DISK\s+FILE\s+ID=n?\d+\]", re.IGNORECASE)


def escape(text: str | None) -> str:
    """Экранировать скобки для описаний задач и форума: `[`→`&#91;`, `]`→`&#93;`."""
    if not text:
        return ""
    return text.replace("[", "&#91;").replace("]", "&#93;")


def _break_tag(m: re.Match[str]) -> str:
    """`[b]` → `[<ZWSP>b]`: скобка на месте, тег для парсера перестаёт существовать."""
    return f"[{ZWSP}{m.group(0)[1:]}"


def escape_chat(text: str | None) -> str:
    """Заглушить BBCode для чата задачи / im.message.add, сохранив текст дословно.

    Глушатся теги `[tag]`, `[/tag]`, `[tag=…]`, маркер списка `[*]` и маркеры вложений;
    индексы вроде `arr[0]` не трогаются.
    """
    if not text:
        return ""
    out = _ANY_TAG_RE.sub(_break_tag, text)
    out = _LIST_ITEM_RE.sub(_break_tag, out)
    return _DISK_RE.sub(_break_tag, out)


def convert(text: str | None) -> str:
    """Обратная операция для чтения: сущности скобок → `[`/`]`, ZWSP снимается."""
    if not text:
        return ""
    return text.replace("&#91;", "[").replace("&#93;", "]").replace(ZWSP, "")
