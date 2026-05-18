"""Minimal Cosmos-SDK Tx builder + signer + REST client for Kava.

Why: Биржевые `kava1...` адреса — это Cosmos-side банковские аккаунты.
Депозитные индексаторы CEX слушают события `cosmos.bank.v1beta1.MsgSend`
на Cosmos-стороне, а не EVM `Transfer` логи. Перевод через Kava EVM
формально увеличивает баланс (precisebank module), но CEX депозит
кредитуется только если транзакция пришла как Cosmos MsgSend.

Реализация:
  * Чистый manual protobuf-encoding (только varint + length-delimited).
  * secp256k1 sign через `coincurve` (зависимость web3, уже установлен).
  * SIGN_MODE_DIRECT: SHA256(SignDoc) → ECDSA → 64-байт (r||s).
  * PubKey type_url = `/ethermint.crypto.v1.ethsecp256k1.PubKey`
    (Kava — ethermint-cosmos chain, ключи eth_secp256k1).
  * REST broadcast: `POST /cosmos/tx/v1beta1/txs` mode SYNC.
  * Account/balance query: `GET /cosmos/{auth,bank}/v1beta1/...`.

Не используется `cosmpy` потому что он не поддерживает ethermint-pubkey
из коробки, а тащить тяжёлый proto-стек ради 1 сообщения избыточно.
"""
from __future__ import annotations

import base64
import hashlib
from typing import List, Optional, Tuple

import coincurve
import requests

# ---------------------------------------------------------------------------
# Protobuf wire encoding
# ---------------------------------------------------------------------------

_WT_VARINT = 0
_WT_LEN = 2


def _varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("varint negative")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field: int, wt: int) -> bytes:
    return _varint((field << 3) | wt)


def _f_varint(field: int, v: int) -> bytes:
    return _tag(field, _WT_VARINT) + _varint(int(v))


def _f_bytes(field: int, v: bytes) -> bytes:
    return _tag(field, _WT_LEN) + _varint(len(v)) + v


def _f_string(field: int, v: str) -> bytes:
    return _f_bytes(field, v.encode("utf-8"))


# ---------------------------------------------------------------------------
# Cosmos proto messages
# ---------------------------------------------------------------------------

PUBKEY_TYPE_URL = "/ethermint.crypto.v1.ethsecp256k1.PubKey"
MSG_SEND_TYPE_URL = "/cosmos.bank.v1beta1.MsgSend"
SIGN_MODE_DIRECT = 1


def _enc_coin(denom: str, amount: str) -> bytes:
    """cosmos.base.v1beta1.Coin { string denom = 1; string amount = 2 }"""
    return _f_string(1, denom) + _f_string(2, amount)


def _enc_any(type_url: str, value: bytes) -> bytes:
    """google.protobuf.Any { string type_url = 1; bytes value = 2 }"""
    return _f_string(1, type_url) + _f_bytes(2, value)


def _enc_msg_send(from_addr: str, to_addr: str, denom: str, amount: str) -> bytes:
    """cosmos.bank.v1beta1.MsgSend"""
    return (
        _f_string(1, from_addr)
        + _f_string(2, to_addr)
        + _f_bytes(3, _enc_coin(denom, amount))
    )


def _enc_pubkey_ethsecp256k1(pub_compressed: bytes) -> bytes:
    """ethermint.crypto.v1.ethsecp256k1.PubKey { bytes key = 1 }"""
    return _f_bytes(1, pub_compressed)


def _enc_tx_body(msgs_any: List[bytes], memo: str = "", timeout_height: int = 0) -> bytes:
    """cosmos.tx.v1beta1.TxBody { repeated Any messages = 1; string memo = 2; uint64 timeout_height = 3 }"""
    out = b""
    for m in msgs_any:
        out += _f_bytes(1, m)
    if memo:
        out += _f_string(2, memo)
    if timeout_height:
        out += _f_varint(3, timeout_height)
    return out


def _enc_mode_info_single(mode: int = SIGN_MODE_DIRECT) -> bytes:
    """cosmos.tx.v1beta1.ModeInfo { Single single = 1 { SignMode mode = 1 } }"""
    single = _f_varint(1, mode)
    return _f_bytes(1, single)


def _enc_signer_info(pubkey_any: bytes, mode_info: bytes, sequence: int) -> bytes:
    """cosmos.tx.v1beta1.SignerInfo"""
    return (
        _f_bytes(1, pubkey_any)
        + _f_bytes(2, mode_info)
        + _f_varint(3, sequence)
    )


def _enc_fee(amount_coins: List[bytes], gas_limit: int) -> bytes:
    """cosmos.tx.v1beta1.Fee { repeated Coin amount = 1; uint64 gas_limit = 2 }"""
    out = b""
    for c in amount_coins:
        out += _f_bytes(1, c)
    out += _f_varint(2, gas_limit)
    return out


def _enc_auth_info(signer_infos: List[bytes], fee: bytes) -> bytes:
    """cosmos.tx.v1beta1.AuthInfo"""
    out = b""
    for si in signer_infos:
        out += _f_bytes(1, si)
    out += _f_bytes(2, fee)
    return out


def _enc_sign_doc(body_bytes: bytes, auth_info_bytes: bytes,
                  chain_id: str, account_number: int) -> bytes:
    """cosmos.tx.v1beta1.SignDoc"""
    return (
        _f_bytes(1, body_bytes)
        + _f_bytes(2, auth_info_bytes)
        + _f_string(3, chain_id)
        + _f_varint(4, account_number)
    )


def _enc_tx_raw(body_bytes: bytes, auth_info_bytes: bytes, signature: bytes) -> bytes:
    """cosmos.tx.v1beta1.TxRaw"""
    return (
        _f_bytes(1, body_bytes)
        + _f_bytes(2, auth_info_bytes)
        + _f_bytes(3, signature)
    )


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------

def _priv_bytes(priv_hex: str) -> bytes:
    s = priv_hex.lower().removeprefix("0x")
    return bytes.fromhex(s)


def priv_to_pub_compressed(priv_hex: str) -> bytes:
    """secp256k1 private key (hex) → 33-byte compressed public key."""
    pk = coincurve.PrivateKey(_priv_bytes(priv_hex))
    return pk.public_key.format(compressed=True)


def _sign_eth_secp256k1(priv_hex: str, payload: bytes) -> bytes:
    """SIGN_MODE_DIRECT signature for ethermint eth_secp256k1.

    КРИТИЧНО: ethermint PubKey.VerifySignature(msg=SignDoc bytes, sig) хэширует
    `msg` через Keccak256, а не SHA256, даже для SIGN_MODE_DIRECT. Это отличие
    от ванильного Cosmos SDK (там SHA256). Если использовать SHA256 — нода
    отдаст code=4 'signature verification failed'. См.:
    https://github.com/evmos/ethermint/blob/main/crypto/ethsecp256k1/ethsecp256k1.go
    """
    from eth_hash.auto import keccak
    pk = coincurve.PrivateKey(_priv_bytes(priv_hex))
    digest = keccak(payload)
    # sign_recoverable: 65 bytes (r||s||v). Cosmos wants just r||s.
    rec = pk.sign_recoverable(digest, hasher=None)
    return rec[:64]


# ---------------------------------------------------------------------------
# High-level: build & sign single-MsgSend tx
# ---------------------------------------------------------------------------

def build_signed_msgsend(
    *,
    priv_hex: str,
    from_addr: str,
    to_addr: str,
    denom: str,
    amount: int,
    chain_id: str,
    account_number: int,
    sequence: int,
    fee_amount: int,
    gas_limit: int,
    memo: str = "",
) -> bytes:
    """Собрать и подписать TxRaw c одним MsgSend. Возвращает bytes для broadcast."""
    pub_c = priv_to_pub_compressed(priv_hex)
    msg_send = _enc_msg_send(from_addr, to_addr, denom, str(amount))
    msg_any = _enc_any(MSG_SEND_TYPE_URL, msg_send)
    body = _enc_tx_body([msg_any], memo=memo)

    pub_proto = _enc_pubkey_ethsecp256k1(pub_c)
    pub_any = _enc_any(PUBKEY_TYPE_URL, pub_proto)
    mode_info = _enc_mode_info_single(SIGN_MODE_DIRECT)
    signer_info = _enc_signer_info(pub_any, mode_info, sequence)

    fee_coin = _enc_coin(denom, str(fee_amount))
    fee = _enc_fee([fee_coin], gas_limit)
    auth_info = _enc_auth_info([signer_info], fee)

    sign_doc = _enc_sign_doc(body, auth_info, chain_id, account_number)
    sig = _sign_eth_secp256k1(priv_hex, sign_doc)

    return _enc_tx_raw(body, auth_info, sig)


def tx_hash_hex(tx_raw_bytes: bytes) -> str:
    """Cosmos tx hash = uppercase hex of SHA256(tx_bytes). Returns lowercased '0x'-prefixed для unifikation."""
    return hashlib.sha256(tx_raw_bytes).hexdigest().upper()


# ---------------------------------------------------------------------------
# Kava REST client
# ---------------------------------------------------------------------------

class KavaRestError(RuntimeError):
    pass


class KavaRestClient:
    """Минимальный клиент Kava LCD REST API."""

    def __init__(self, base_url: str, proxy: Optional[str] = None,
                 timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if proxy:
            try:
                from modules.proxy_manager import parse_proxy
                purl = parse_proxy(proxy)
                if purl:
                    self.session.proxies = {"http": purl, "https": purl}
            except Exception:
                pass

    # --- queries ---

    def get_account(self, address: str) -> Tuple[int, int]:
        """Returns (account_number, sequence). Raises if not found.

        Поддерживает оба формата ответа:
          - BaseAccount: {account: {account_number, sequence, ...}}
          - EthAccount:  {account: {base_account: {account_number, sequence}}}
        """
        url = f"{self.base}/cosmos/auth/v1beta1/accounts/{address}"
        r = self.session.get(url, timeout=self.timeout)
        if r.status_code == 404:
            raise KavaRestError(
                f"account {address} not found (404). "
                f"Кошелёк ещё не появлялся в Cosmos state — "
                f"отправь сначала любой incoming или используй другую сеть."
            )
        if not r.ok:
            raise KavaRestError(f"GET {url} → HTTP {r.status_code}: {r.text[:200]}")
        data = r.json().get("account") or {}
        if "base_account" in data:
            data = data["base_account"]
        try:
            return int(data["account_number"]), int(data.get("sequence") or 0)
        except (KeyError, ValueError, TypeError) as exc:
            raise KavaRestError(f"unexpected account shape: {data!r} ({exc})")

    def get_balance(self, address: str, denom: str = "ukava") -> int:
        """Bank balance в наименьших единицах (ukava). 0 если нет такого denom."""
        url = f"{self.base}/cosmos/bank/v1beta1/balances/{address}/by_denom"
        r = self.session.get(url, params={"denom": denom}, timeout=self.timeout)
        if not r.ok:
            raise KavaRestError(f"GET {url} → HTTP {r.status_code}: {r.text[:200]}")
        bal = r.json().get("balance") or {}
        return int(bal.get("amount") or 0)

    def broadcast_tx(self, tx_raw_bytes: bytes,
                     mode: str = "BROADCAST_MODE_SYNC") -> dict:
        """POST /cosmos/tx/v1beta1/txs. Возвращает разобранный JSON.

        Внутри ответ имеет поле `tx_response` с {code, txhash, raw_log, ...}.
        code=0 → принято в mempool (но финальность ещё надо проверить get_tx).
        """
        url = f"{self.base}/cosmos/tx/v1beta1/txs"
        payload = {
            "tx_bytes": base64.b64encode(tx_raw_bytes).decode("ascii"),
            "mode": mode,
        }
        r = self.session.post(url, json=payload, timeout=self.timeout)
        if not r.ok:
            raise KavaRestError(f"POST {url} → HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def get_tx(self, tx_hash: str) -> Optional[dict]:
        """GET /cosmos/tx/v1beta1/txs/{hash}. None если ещё не в блоке (404)."""
        h = tx_hash.removeprefix("0x").upper()
        url = f"{self.base}/cosmos/tx/v1beta1/txs/{h}"
        r = self.session.get(url, timeout=self.timeout)
        if r.status_code == 404:
            return None
        if not r.ok:
            raise KavaRestError(f"GET {url} → HTTP {r.status_code}: {r.text[:200]}")
        return r.json()


__all__ = [
    "PUBKEY_TYPE_URL",
    "MSG_SEND_TYPE_URL",
    "SIGN_MODE_DIRECT",
    "build_signed_msgsend",
    "tx_hash_hex",
    "priv_to_pub_compressed",
    "KavaRestClient",
    "KavaRestError",
]
