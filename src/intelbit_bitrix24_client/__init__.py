"""Apache-клиент Bitrix24 REST — общий для Интелбит MCP (4-23) и Река-коннектора."""

from intelbit_bitrix24_client.client import BATCH_MAX, PAGE_SIZE, Bitrix24Client, flatten
from intelbit_bitrix24_client.errors import Bitrix24Error, QueryLimitExceeded
from intelbit_bitrix24_client.ratelimit import TokenBucket

__version__ = "0.2.0"

__all__ = [
    "BATCH_MAX",
    "PAGE_SIZE",
    "Bitrix24Client",
    "Bitrix24Error",
    "QueryLimitExceeded",
    "TokenBucket",
    "flatten",
]
