"""Pharos Claim Claimer — он-чейн исполнение клейма.

Флоу (полностью эмулирует поведение фронта claim.pharos.xyz):

  1. warmup + auth (см. checker.ClaimChecker) — токен нужен только если бы мы
     хотели вызвать /airdrop/airdrop_info; сам клейм идёт в обход API.
  2. GET https://claim.pharos.xyz/api/proxy/proof?tier=<tier>&hash=<md5>
        md5 = md5("pharosairdrop" + tier + addr_lower[2:5])
        ответ: JSON-массив записей вида [address, amount, merkleRoot, merkleProof[]]
        фильтруем по address.lower() == self.address.lower()
  3. encode tier как viem stringToHex(tier, {size:32}) → bytes32 right-padded.
  4. on-chain: claim(tier, amount, merkleProof) на CLAIM_CONTRACT_ADDRESS,
     отправляется через web3.py с подписью локальным аккаунтом.

Используется тот же curl_cffi-сeссионный паттерн (с прокси), что и у чекера:
прокси нужен для запросов к claim.pharos.xyz / api.claim.pharos.xyz.
RPC-вызовы (web3) идут НАПРЯМУЮ, без прокси (RPC-узел не за CF).
"""
from __future__ import annotations

import hashlib
import random
import time
from typing import Callable, Optional

from curl_cffi import requests as curl_requests
from eth_account import Account
from fake_useragent import FakeUserAgent
from web3 import Web3
from web3.middleware import geth_poa_middleware

from config.modules.cfg_base import RETRY_COUNT, SLEEP_BETWEEN_ACTIONS
from config.modules.cfg_pharos_claim import (
    CLAIM_CHAIN_ID,
    CLAIM_CONTRACT_ABI,
    CLAIM_CONTRACT_ADDRESS,
    CLAIM_DEFAULT_TIER,
    CLAIM_EXPLORER_TX,
    CLAIM_GAS_LIMIT,
    CLAIM_GAS_PRICE_BUFFER,
    CLAIM_HEADERS,
    CLAIM_IMPERSONATE,
    CLAIM_REQUEST_TIMEOUT,
    CLAIM_RPC_URL,
    CLAIM_TX_TIMEOUT,
    CLAIM_WAIT_FOR_RECEIPT,
    PROOF_ENDPOINT,
    PROOF_HASH_PREFIX,
    SITE_URL,
)
from modules.proxy_manager import parse_proxy
from modules.simple_logger import logger as _logger

_ua = FakeUserAgent()


# ─────────────────── результат ───────────────────

class ClaimActionResult:
    """Структурированный результат одной попытки клейма."""

    __slots__ = (
        "ok", "tx_hash", "amount", "tier", "already_claimed",
        "skip_reason", "error", "raw_proof", "not_ready",
    )

    def __init__(
        self,
        *,
        ok: bool = False,
        tx_hash: Optional[str] = None,
        amount: Optional[str] = None,
        tier: Optional[str] = None,
        already_claimed: bool = False,
        skip_reason: Optional[str] = None,
        error: Optional[str] = None,
        raw_proof: Optional[dict] = None,
        not_ready: bool = False,
    ) -> None:
        self.ok = ok
        self.tx_hash = tx_hash
        self.amount = amount
        self.tier = tier
        self.already_claimed = already_claimed
        self.skip_reason = skip_reason
        self.error = error
        self.raw_proof = raw_proof
        self.not_ready = not_ready


def _short(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}"


def _log(level: str, msg: str, address: str) -> None:
    getattr(_logger.bind(wallet=_short(address)), level)(msg)


# ─────────────────── утилиты для proof / tier ───────────────────

def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _build_proof_url(tier: str, address: str) -> str:
    """Воссоздать URL так же, как фронт.

      addr_lower[2:5] — первые 3 hex-символа адреса после `0x`.
      hash = md5("pharosairdrop" + tier + addr_lower[2:5])
    """
    addr_lower = address.lower()
    prefix3 = addr_lower[2:5]
    hash_hex = _md5_hex(PROOF_HASH_PREFIX + tier + prefix3)
    base = SITE_URL.rstrip("/")
    return f"{base}{PROOF_ENDPOINT}?tier={tier}&hash={hash_hex}"


def _tier_to_bytes32(tier: str) -> bytes:
    """Эквивалент viem stringToHex(tier, {size:32}) — right-padded zeros."""
    raw = tier.encode("utf-8")
    if len(raw) > 32:
        raise ValueError(f"tier '{tier}' длиннее 32 байт")
    return raw + b"\x00" * (32 - len(raw))


# ─────────────────── клиент ───────────────────

class ClaimClaimer:
    """Один аккаунт = одна сессия curl_cffi (для proof) + один web3-вызов."""

    def __init__(self, private_key: str, proxy: Optional[str]) -> None:
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        self._account = Account.from_key(private_key)
        self.address: str = self._account.address
        self.proxy: Optional[str] = proxy
        self.user_agent: str = _ua.random
        self._session: curl_requests.Session = self._build_session()
        self._w3: Optional[Web3] = None  # ленивая инициализация

    def _build_session(self) -> curl_requests.Session:
        sess = curl_requests.Session(impersonate=CLAIM_IMPERSONATE)
        sess.headers.update({**CLAIM_HEADERS, "User-Agent": self.user_agent})
        normalized = parse_proxy(self.proxy)
        if normalized:
            sess.proxies = {"http": normalized, "https": normalized}
        return sess

    def _get_web3(self) -> Web3:
        if self._w3 is None:
            w3 = Web3(Web3.HTTPProvider(CLAIM_RPC_URL, request_kwargs={"timeout": 30}))
            # На всякий случай — Pharos может отдавать PoA extraData.
            try:
                w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            except Exception:
                pass
            self._w3 = w3
        return self._w3

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    # ───────── proof ─────────
    def fetch_merkle_proof(self, tier: str) -> tuple[Optional[dict], Optional[str]]:
        """Скачать merkleProof по адресу/тиру. Возвращает (entry_dict, error)."""
        url = _build_proof_url(tier, self.address)
        try:
            resp = self._session.get(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Sec-Fetch-Site": "same-origin",
                },
                timeout=CLAIM_REQUEST_TIMEOUT,
            )
        except Exception as e:
            return None, f"proof request failed: {type(e).__name__}: {str(e)[:160]}"

        preview = (resp.text or "")[:200].replace("\n", " ")
        if resp.status_code == 404:
            # Сайт явно отвечает 404, если merkle-файла для (tier, hash) нет
            # — значит адрес не входит в раздачу этого тира.
            return None, f"not in merkle tree for tier='{tier}' (HTTP 404)"
        if resp.status_code != 200:
            return None, f"proof HTTP {resp.status_code}: {preview}"
        try:
            body = resp.json()
        except Exception as e:
            return None, f"proof json parse: {e} | {preview}"

        if not isinstance(body, list):
            return None, f"proof unexpected shape: {preview}"

        addr_lower = self.address.lower()
        for entry in body:
            if not isinstance(entry, list) or len(entry) < 4:
                continue
            try:
                if str(entry[0]).lower() == addr_lower:
                    return {
                        "address": entry[0],
                        "amount": str(entry[1]),
                        "merkleRoot": entry[2],
                        "merkleProof": list(entry[3]),
                    }, None
            except Exception:
                continue

        return None, "address not found in merkle file"

    # ───────── on-chain ─────────
    def has_claimed_onchain(self) -> Optional[bool]:
        """Прочитать hasClaimed(address) с контракта. None при ошибке RPC."""
        try:
            w3 = self._get_web3()
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(CLAIM_CONTRACT_ADDRESS),
                abi=CLAIM_CONTRACT_ABI,
            )
            return bool(
                contract.functions.hasClaimed(
                    Web3.to_checksum_address(self.address)
                ).call()
            )
        except Exception as e:
            _log("debug", f"hasClaimed RPC failed: {type(e).__name__}: {e}", self.address)
            return None

    def submit_claim_tx(
        self,
        tier: str,
        amount_wei: int,
        merkle_proof: list[str],
    ) -> tuple[Optional[str], Optional[str]]:
        """Подписать и отправить claim(...). Возвращает (tx_hash_hex, error)."""
        try:
            w3 = self._get_web3()
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(CLAIM_CONTRACT_ADDRESS),
                abi=CLAIM_CONTRACT_ABI,
            )

            tier_b32 = _tier_to_bytes32(tier)
            proof_bytes = []
            for p in merkle_proof:
                if not isinstance(p, str):
                    return None, f"proof item not a string: {p!r}"
                p_clean = p[2:] if p.startswith("0x") else p
                if len(p_clean) != 64:
                    return None, f"proof item wrong length: {p}"
                proof_bytes.append(bytes.fromhex(p_clean))

            from_addr = Web3.to_checksum_address(self.address)
            try:
                gas_price = int(w3.eth.gas_price * CLAIM_GAS_PRICE_BUFFER)
            except Exception:
                gas_price = w3.to_wei("1", "gwei")

            nonce = w3.eth.get_transaction_count(from_addr)

            tx = contract.functions.claim(
                tier_b32, int(amount_wei), proof_bytes,
            ).build_transaction({
                "from": from_addr,
                "nonce": nonce,
                "gas": CLAIM_GAS_LIMIT,
                "gasPrice": gas_price,
                "chainId": CLAIM_CHAIN_ID,
            })

            signed = self._account.sign_transaction(tx)
            raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction")
            tx_hash = w3.eth.send_raw_transaction(raw)
            tx_hash_hex = tx_hash.hex()
            if not tx_hash_hex.startswith("0x"):
                tx_hash_hex = "0x" + tx_hash_hex

            if CLAIM_WAIT_FOR_RECEIPT:
                try:
                    rcpt = w3.eth.wait_for_transaction_receipt(
                        tx_hash, timeout=CLAIM_TX_TIMEOUT
                    )
                    if rcpt.status != 1:
                        return tx_hash_hex, f"tx reverted (status=0): {tx_hash_hex}"
                except Exception as e:
                    return tx_hash_hex, f"wait receipt: {type(e).__name__}: {str(e)[:160]}"

            return tx_hash_hex, None
        except Exception as e:
            return None, f"send tx: {type(e).__name__}: {str(e)[:200]}"

    # ───────── главный метод ─────────
    def claim(
        self,
        *,
        tier: Optional[str] = None,
        amount_wei: Optional[int] = None,
    ) -> ClaimActionResult:
        """Полный сценарий: hasClaimed → proof → claim().

        tier и amount_wei можно передать заранее (из airdrop_info чекера).
        Если не переданы — tier берётся из CLAIM_DEFAULT_TIER, amount — из proof-записи.
        """
        tier_eff = (tier or CLAIM_DEFAULT_TIER).strip()
        if not tier_eff:
            return ClaimActionResult(error="empty tier")

        # 1. Уже клеймили on-chain? Тогда нет смысла идти за proof.
        on_chain_claimed = self.has_claimed_onchain()
        if on_chain_claimed is True:
            return ClaimActionResult(
                ok=True,
                already_claimed=True,
                tier=tier_eff,
                skip_reason="hasClaimed=true on-chain",
            )

        # 2. Тащим merkleProof.
        proof_entry, err = self.fetch_merkle_proof(tier_eff)
        if err:
            # 404 от сайта значит «merkle-файл для (tier, prefix) не опубликован» —
            # это состояние «backend ещё не раздал пруф», а не отказ. Помечаем задачу
            # как not_ready, чтобы она автоматически перепроверилась при следующем запуске.
            if "HTTP 404" in err or "not in merkle tree" in err:
                return ClaimActionResult(
                    not_ready=True,
                    tier=tier_eff,
                    skip_reason=f"proof not published yet on server: {err}",
                )
            return ClaimActionResult(error=f"proof: {err}", tier=tier_eff)

        if amount_wei is None:
            try:
                amount_wei = int(proof_entry["amount"])
            except (TypeError, ValueError, KeyError):
                return ClaimActionResult(
                    error=f"proof has invalid amount: {proof_entry.get('amount')!r}",
                    tier=tier_eff,
                    raw_proof=proof_entry,
                )

        # 3. Шлём транзакцию.
        tx_hash, err = self.submit_claim_tx(
            tier_eff, int(amount_wei), proof_entry["merkleProof"],
        )
        if err:
            return ClaimActionResult(
                error=err,
                tx_hash=tx_hash,
                tier=tier_eff,
                raw_proof=proof_entry,
            )

        # Человекочитаемая сумма (PHRS, 18 dec)
        try:
            amt_human = f"{int(amount_wei) / 10 ** 18:.4f}".rstrip("0").rstrip(".") or "0"
            amount_str = f"{amt_human} PHRS"
        except Exception:
            amount_str = str(amount_wei)

        return ClaimActionResult(
            ok=True,
            tx_hash=tx_hash,
            amount=amount_str,
            tier=tier_eff,
            raw_proof=proof_entry,
        )


# ─────────────────── ретраи + ротация прокси ───────────────────

def claim_wallet_with_retry(
    private_key: str,
    proxy: Optional[str],
    *,
    tier: Optional[str] = None,
    amount_wei: Optional[int] = None,
    on_proxy_rotate: Optional[Callable[[], Optional[str]]] = None,
) -> ClaimActionResult:
    """Попытаться клейм с ретраями.

    Ретраимся ТОЛЬКО на сетевых/HTTP/RPC ошибках. Если транзакция уже отправлена
    (есть tx_hash) — считаем результат финальным, чтобы не плодить дубли.
    """
    current_proxy = proxy
    attempts = max(1, int(RETRY_COUNT))
    last: Optional[ClaimActionResult] = None
    address_for_log = "0x????"

    for attempt in range(1, attempts + 1):
        claimer = ClaimClaimer(private_key, current_proxy)
        address_for_log = claimer.address
        try:
            result = claimer.claim(tier=tier, amount_wei=amount_wei)
        finally:
            claimer.close()

        last = result

        # Успех — выходим.
        if result.ok:
            return result

        # Транзакция уже улетела (tx_hash есть) — больше не ретраим.
        if result.tx_hash:
            return result

        # Proof ещё не опубликован сервером — нет смысла ретраить в рамках
        # текущего запуска, на другом прокси результат будет тот же.
        if result.not_ready:
            return result

        _log(
            "warning",
            f"Попытка {attempt}/{attempts}: {result.error}",
            address_for_log,
        )

        if attempt < attempts:
            if on_proxy_rotate is not None:
                new_proxy = on_proxy_rotate()
                if new_proxy and new_proxy != current_proxy:
                    current_proxy = new_proxy
                    _log("info", "Прокси заменён, повтор…", address_for_log)
            time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

    return last or ClaimActionResult(error="unknown error")


# ─────────────────── ссылка в эксплорере (для UI) ───────────────────

def explorer_url(tx_hash: str) -> str:
    return f"{CLAIM_EXPLORER_TX.rstrip('/')}/{tx_hash}"
