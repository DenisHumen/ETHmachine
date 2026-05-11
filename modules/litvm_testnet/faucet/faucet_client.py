"""LiteForge faucet client.

Vercel BotID на хабе блокирует ВСЁ что не из браузера (cookies + JA3 + ...),
поэтому tRPC вызов делается из patchright через `VercelClient` (см.
modules/litvm_testnet/vercel_bypass.py). Здесь — только высокоуровневая
обёртка: классификация ошибок сервера и нормализация полей.

tRPC procedure (реверс-инжиниринг JS-бандла liteforge.hub.caldera.xyz):
    POST /api/trpc/faucet.requestFaucetFunds?batch=1
    body: {"0":{"json":{
        "rollupSubdomain": "liteforge",
        "recipientAddress": "0x...",
        "turnstileToken": "<solved CF Turnstile token>"
    }}}
    response: [{"result":{"data":{"json":{
        "success": bool,
        "message": str,
        # на успехе обычно также: transactionHash, amount, ...
    }}}}]
"""
from __future__ import annotations

from typing import Optional, Tuple

from config.modules.cfg_litvm_testnet import (
    LITVM_FAUCET_CAPTCHA_SITEKEY,
    LITVM_FAUCET_ROLLUP_SUBDOMAIN,
    LITVM_FAUCET_URL,
)
from modules.litvm_testnet.vercel_bypass import (
    VercelBypassError,
    VercelCheckpointError,
    get_client,
)


# Сообщения сервера-крана, по которым понимаем что заявка под кулдауном.
# Базируются на текстах ответа Caldera Hub (English).
_COOLDOWN_MARKERS = (
    "rate limit", "rate-limit",
    "already claimed", "already received",
    "wait 24", "24 hour", "24h",
    "try again later", "cooldown",
    "limit reached", "one request", "one claim",
    "already requested",
    "too many requests",
)

# Маркеры "кошелёк не подходит" — ретрай не поможет.
_INELIGIBLE_MARKERS = (
    "not eligible", "invalid address",
    "blacklist", "blocked",
    "disabled",
    "faucet not enabled",
    "hidefaucet",
)

# Маркеры провала Turnstile валидации — нужно пересолвить капчу и попробовать снова.
_CAPTCHA_FAIL_MARKERS = (
    "missing turnstile",
    "validating your request",
    "invalid captcha",
    "captcha failed",
    "invalid turnstile",
)

# Server-side faucet wallet не смог отправить tx (nonce/RPC race на стороне
# Caldera Hub). При этом наш turnstile token уже валиден — пересолвливать
# капчу не нужно, нужно просто подождать пока серверный signer стабилизируется.
_SERVER_BUSY_MARKERS = (
    "failed to send transaction",
    "failed to send tx",
    "nonce too low",
    "replacement transaction underpriced",
    "internal server error",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "timeout",
)


class LitvmFaucetError(Exception):
    pass


class LitvmFaucetCooldownError(LitvmFaucetError):
    """Сервер ответил, что заявка уже подана / лимит исчерпан."""


class LitvmFaucetCaptchaError(LitvmFaucetError):
    """Сервер отверг turnstile token — нужно пересолвить капчу."""


class LitvmFaucetVercelChallenge(LitvmFaucetError):
    """В ответ пришёл Vercel Security Checkpoint."""


def classify_error(message: str) -> str:
    """'cooldown' | 'ineligible' | 'captcha' | 'server_busy' | 'transient'."""
    low = (message or "").lower()
    for m in _COOLDOWN_MARKERS:
        if m in low:
            return "cooldown"
    for m in _INELIGIBLE_MARKERS:
        if m in low:
            return "ineligible"
    for m in _CAPTCHA_FAIL_MARKERS:
        if m in low:
            return "captcha"
    for m in _SERVER_BUSY_MARKERS:
        if m in low:
            return "server_busy"
    return "transient"


def submit_claim(
    proxy: Optional[str],
    wallet: str,
    turnstile_token: str,
) -> Tuple[bool, Optional[str], str]:
    """Делает tRPC mutation faucet.requestFaucetFunds через браузерный контекст.
    Возвращает (success, tx_hash, raw_message).

    Поднимает LitvmFaucetCooldownError, LitvmFaucetCaptchaError или
    LitvmFaucetVercelChallenge — caller решает что делать."""
    try:
        result = get_client().submit_faucet_request(
            proxy=proxy,
            rollup_subdomain=LITVM_FAUCET_ROLLUP_SUBDOMAIN,
            recipient_address=wallet,
            turnstile_token=turnstile_token,
        )
    except VercelCheckpointError as e:
        raise LitvmFaucetVercelChallenge(str(e)) from e
    except VercelBypassError as e:
        raise LitvmFaucetError(f"browser submit failed: {e}") from e

    # tRPC-уровневая ошибка (zod / unauthorized / etc.)
    if result.get("_trpc_error"):
        msg = result.get("message") or "tRPC error"
        # zodError содержит расшифровку — но обычно для наших полей не сработает
        raise LitvmFaucetError(f"tRPC error: {str(msg)[:200]}")

    success = bool(result.get("success"))
    # На разных Caldera-хабах ключ tx hash немного различается.
    tx_hash = (
        result.get("transactionHash")
        or result.get("txHash")
        or result.get("hash")
        or result.get("tx")
    )
    message = str(result.get("message") or "").strip() or ("ok" if success else "fail")

    if success and tx_hash:
        return True, str(tx_hash), message
    if success:
        # Успех без tx_hash — редко, но фиксируем как success
        return True, None, message

    kind = classify_error(message)
    if kind == "cooldown":
        raise LitvmFaucetCooldownError(message)
    if kind == "captcha":
        raise LitvmFaucetCaptchaError(message)
    # ineligible/transient — отдаём наверх для классификации в worker
    return False, None, message


def warmup_proxy(proxy: Optional[str]) -> None:
    """Прогревает браузерный контекст для proxy (открыть страницу, пройти
    checkpoint, чтобы первый submit_claim был быстрым)."""
    try:
        get_client().warmup(proxy)
    except VercelBypassError as e:
        raise LitvmFaucetError(f"warmup failed: {e}") from e


# Удобные алиасы для импорта в worker.py
CAPTCHA_SITEKEY = LITVM_FAUCET_CAPTCHA_SITEKEY
CAPTCHA_PAGEURL = LITVM_FAUCET_URL


# ---------------------------------------------------------------------------
# Stub-ы для обратной совместимости с уже написанным worker.py.
# Они больше не нужны функционально (нет HTTP — всё через браузер), но
# поддерживают существующие импорты пока worker не обновлён.
# ---------------------------------------------------------------------------

_TEST_SITEKEYS = {
    "10000000-ffff-ffff-ffff-000000000001",
    "20000000-ffff-ffff-ffff-000000000002",
    "1x00000000000000000000AA",
    "2x00000000000000000000AB",
    "3x00000000000000000000FF",
    "6Lc_aCMTAAAAABx7u2N0D1XnVbI_v6ZdbM6rYf16",
}


def is_test_sitekey(sitekey: str) -> bool:
    return (sitekey or "").strip() in _TEST_SITEKEYS


def resolve_sitekey(_session=None, auto: bool = False, fallback: str = "") -> Tuple[str, str]:
    """Sitekey зашит в конфиг (LITVM_FAUCET_CAPTCHA_SITEKEY). Авто-парсинг
    из HTML больше не делаем — он не нужен, sitekey стабильный (виджет
    Turnstile зарегистрирован на домене caldera.xyz)."""
    return fallback or LITVM_FAUCET_CAPTCHA_SITEKEY, "config"


def make_session(proxy=None, vcrcs_cookie=None):
    """Deprecated stub — больше не нужен (все HTTP через VercelClient)."""
    raise RuntimeError(
        "make_session() больше не используется — HTTP идёт через VercelClient. "
        "Это импорт-ошибка, обнови worker.py."
    )
