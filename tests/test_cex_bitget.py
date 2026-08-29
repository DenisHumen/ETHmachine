"""Проверки подписи POST-запросов к Bitget.

Bitget подписывает строку ``timestamp + method + path + body``, где body —
это ровно те байты, что ушли в запросе. Раньше подпись считалась по
компактному ``json.dumps(..., separators=(',', ':'))``, а тело отправлялось
через ``json=data``: requests пересобирал его с пробелами после ``:`` и ``,``,
поэтому подпись никогда не сходилась и биржа отбивала каждый POST.
Сеть не используется — session подменяется заглушкой.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from modules.cex.bitget import bitget_SubAccount


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    """Заглушка requests.Session: запоминает вызов вместо похода в сеть."""

    def __init__(self):
        self.headers = {}
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _FakeResponse({"code": "00000", "data": []})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _FakeResponse({"code": "00000", "data": []})


@pytest.fixture()
def client():
    c = bitget_SubAccount.BitgetClient("key", "secret", "pass")
    c.session = _FakeSession()
    return c


def test_post_sends_exactly_the_signed_body(client):
    """Тело POST должно совпадать со строкой, по которой посчитана подпись."""
    payload = {"coin": "USDT", "amount": "1.5", "fromType": "spot"}
    client._make_request("POST", "/api/v2/spot/wallet/transfer", data=payload)

    _, _, kwargs = client.session.calls[0]
    body = kwargs["data"]
    headers = kwargs["headers"]

    # requests с json=... вставил бы пробелы — тело обязано остаться компактным
    assert body == json.dumps(payload, separators=(",", ":"))
    assert json.loads(body) == payload

    sign_str = (
        headers["ACCESS-TIMESTAMP"] + "POST" + "/api/v2/spot/wallet/transfer" + body
    )
    expected = base64.b64encode(
        hmac.new(b"secret", sign_str.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    assert headers["ACCESS-SIGN"] == expected


def test_post_without_body_signs_empty_string(client):
    """Без тела подпись считается по пустой строке, и тело остаётся пустым."""
    client._make_request("POST", "/api/v2/spot/account/info")

    _, _, kwargs = client.session.calls[0]
    assert kwargs["data"] == ""

    headers = kwargs["headers"]
    sign_str = headers["ACCESS-TIMESTAMP"] + "POST" + "/api/v2/spot/account/info"
    expected = base64.b64encode(
        hmac.new(b"secret", sign_str.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    assert headers["ACCESS-SIGN"] == expected
