"""TLS: verify / ca_bundle доходят до httpx и работают с самоподписанным сертификатом."""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import trustme

from intelbit_bitrix24_client import Bitrix24Client
from intelbit_bitrix24_client.errors import Bitrix24Error


@pytest.fixture(scope="module")
def ca() -> trustme.CA:
    return trustme.CA()


@pytest.fixture
async def tls_server(ca: trustme.CA) -> AsyncIterator[int]:
    """Минимальный HTTPS-сервер: на любой POST отвечает конвертом {"result": true}."""
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("127.0.0.1").configure_cert(context)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = 0
            for line in headers.decode().split("\r\n"):
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":")[1])
            await reader.readexactly(length)
            body = json.dumps({"result": True}).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield port


def _url(port: int) -> str:
    return f"https://127.0.0.1:{port}/rest/1/token/"


async def test_ca_bundle_trusts_self_signed(
    tls_server: int, ca: trustme.CA, tmp_path: Path
) -> None:
    ca_file = tmp_path / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_file))
    client = Bitrix24Client(_url(tls_server), ca_bundle=str(ca_file), max_retries=0)
    assert (await client.call("profile"))["result"] is True


async def test_default_verify_rejects_self_signed(tls_server: int) -> None:
    client = Bitrix24Client(_url(tls_server), max_retries=0)
    with pytest.raises(Bitrix24Error) as exc_info:
        await client.call("profile")
    assert exc_info.value.code == "transport_error"
    assert "CERTIFICATE_VERIFY_FAILED" in str(exc_info.value)


async def test_verify_false_accepts(tls_server: int) -> None:
    client = Bitrix24Client(_url(tls_server), verify=False, max_retries=0)
    assert (await client.call("profile"))["result"] is True


async def test_verify_as_path(tls_server: int, ca: trustme.CA, tmp_path: Path) -> None:
    ca_file = tmp_path / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_file))
    client = Bitrix24Client(_url(tls_server), verify=str(ca_file), max_retries=0)
    assert (await client.call("profile"))["result"] is True


def test_ca_bundle_wins_over_verify(tmp_path: Path, ca: trustme.CA) -> None:
    ca_file = tmp_path / "ca.pem"
    ca.cert_pem.write_to_path(str(ca_file))
    client = Bitrix24Client("https://b24/rest/1/t/", verify=False, ca_bundle=str(ca_file))
    assert isinstance(client._verify, ssl.SSLContext)


def test_empty_ca_bundle_ignored() -> None:
    assert Bitrix24Client("https://b24/rest/1/t/", ca_bundle="")._verify is True
    assert Bitrix24Client("https://b24/rest/1/t/", verify=False)._verify is False


def test_missing_ca_bundle_file() -> None:
    with pytest.raises(ValueError, match="CA не найден"):
        Bitrix24Client("https://b24/rest/1/t/", ca_bundle="/nonexistent/ca.pem")
