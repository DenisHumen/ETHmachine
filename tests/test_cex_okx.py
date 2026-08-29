"""Проверки запросов к OKX: тело, подпись и повторы.

Тело POST-запроса к OKX подписывается байт в байт, поэтому подпись и
отправленная строка обязаны совпадать, а сама строка — быть валидным JSON.
Раньше здесь уходил ``str(dict)`` с одинарными кавычками, и биржа
отвергала каждый вывод. Сеть в тестах не используется — ``requests``
подменяется заглушкой.
"""

from __future__ import annotations

import ast
import base64
import collections
import hmac
import json

import pytest

from modules.cex.okx import okx_withdraw
from tests.conftest import PROJECT_ROOT

WITHDRAW_PATH = "/api/v5/asset/withdrawal"
TRANSFER_PATH = "/api/v5/asset/transfer"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeRequests:
    """Заглушка ``requests``: запоминает вызовы вместо похода в сеть."""

    def __init__(self, get_payload=None, post_payload=None):
        self.calls = []
        self._get_payload = get_payload or {"code": "0", "data": []}
        self._post_payload = post_payload or {"code": "0", "data": [{"wdId": "1"}]}

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _FakeResponse(self._get_payload)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _FakeResponse(self._post_payload)

    def posts_to(self, suffix):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith(suffix)]


@pytest.fixture()
def okx_env(monkeypatch):
    """Общее окружение: без сети, без комиссии по API, без sleep между повторами."""
    monkeypatch.setattr(okx_withdraw, "get_withdraw_fee", lambda *a, **kw: 0.1)
    monkeypatch.setattr(okx_withdraw.time, "sleep", lambda *_: None)
    return monkeypatch


def _run_withdraw(monkeypatch, fake, eu_type=1, amount=12.5):
    monkeypatch.setattr(okx_withdraw, "requests", fake)
    monkeypatch.setattr(okx_withdraw, "_get_okx_settings", lambda: (eu_type, []))
    return okx_withdraw.execute_okx_withdraw(
        "0xabc", "USDT", "Arbitrum One", amount, "key", "secret", "pass"
    )


def test_withdraw_body_is_valid_json(okx_env):
    """Тело вывода должно парситься как JSON, а все значения — быть строками."""
    fake = _FakeRequests()
    assert _run_withdraw(okx_env, fake) == 12.5

    posts = fake.posts_to(WITHDRAW_PATH)
    assert len(posts) == 1

    body = posts[0][2]["data"]
    payload = json.loads(body)  # на str(dict) с одинарными кавычками упадёт
    assert payload["ccy"] == "USDT"
    assert payload["amt"] == "12.5"
    assert payload["chain"] == "USDT-Arbitrum One"
    assert payload["toAddr"] == "0xabc"
    assert payload["dest"] == "4"
    assert all(isinstance(v, str) for v in payload.values()), payload


def test_withdraw_signature_matches_sent_body(okx_env):
    """Подпись должна считаться ровно по той строке, что ушла в теле запроса."""
    fake = _FakeRequests()
    _run_withdraw(okx_env, fake)

    _, _, kwargs = fake.posts_to(WITHDRAW_PATH)[0]
    body = kwargs["data"]
    headers = kwargs["headers"]

    message = headers["OK-ACCESS-TIMESTAMP"] + "POST" + WITHDRAW_PATH + body
    expected = base64.b64encode(
        hmac.new(b"secret", message.encode("utf-8"), digestmod="sha256").digest()
    ).decode("utf-8")
    assert headers["OK-ACCESS-SIGN"] == expected


def test_transfer_body_is_valid_json(okx_env):
    """Перевод с торгового счёта на основной тоже уходит как JSON со строками."""
    fake = _FakeRequests(
        get_payload={"code": "0", "data": [{"details": [{"cashBal": "3.5"}]}]}
    )
    _run_withdraw(okx_env, fake, eu_type=0)

    transfers = fake.posts_to(TRANSFER_PATH)
    assert len(transfers) == 1
    assert json.loads(transfers[0][2]["data"]) == {
        "ccy": "USDT",
        "amt": "3.5",
        "from": "18",
        "to": "6",
        "type": "0",
    }


def test_retry_after_exception_keeps_credentials(okx_env):
    """Повтор после исключения не должен сдвигать аргументы и терять ключи API."""

    class _Boom:
        def get(self, *a, **kw):
            raise RuntimeError("сеть недоступна")

        post = get

    okx_env.setattr(okx_withdraw, "requests", _Boom())
    okx_env.setattr(okx_withdraw, "_get_okx_settings", lambda: (1, []))

    seen = []
    original = okx_withdraw.execute_okx_withdraw

    def spy(*args, **kwargs):
        seen.append(args)
        return original(*args, **kwargs)

    okx_env.setattr(okx_withdraw, "execute_okx_withdraw", spy)

    assert spy("0xabc", "USDT", "Arbitrum One", 1.0, "key", "secret", "pass", 1, 1) is None
    assert len(seen) == 4, "ожидаем исходный вызов и три повтора"
    for call in seen:
        assert call[4:7] == ("key", "secret", "pass")
    assert [call[9] if len(call) > 9 else 0 for call in seen] == [0, 1, 2, 3]


@pytest.mark.parametrize(
    "value,expected",
    [
        (1e-06, "0.000001"),  # без экспоненты, иначе OKX не распарсит
        (0.012346, "0.012346"),
        (100.0, "100"),
        (1234.5, "1234.5"),
        (0, "0"),
    ],
)
def test_format_okx_amount(value, expected):
    """Суммы уходят строкой без научной нотации и без хвостовых нулей."""
    assert okx_withdraw.format_okx_amount(value) == expected


def test_no_duplicate_methods_in_cex_modules():
    """Повторное определение метода молча затирает первое — так терялась логика торговли."""
    duplicates = []
    for path in sorted((PROJECT_ROOT / "modules" / "cex").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.Module)):
                continue
            names = collections.Counter(
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            scope = getattr(node, "name", "<module>")
            duplicates += [
                f"{path.relative_to(PROJECT_ROOT)}::{scope}::{name}"
                for name, count in names.items()
                if count > 1
            ]
    assert not duplicates, f"дублирующиеся определения: {duplicates}"
