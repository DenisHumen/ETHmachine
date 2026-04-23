"""Pharos Tier Registrar — регистрация "Instant Airdrop" до даты клейма.

Реплицирует действие кнопки Confirm на claim.pharos.xyz: выбор опции
(Instant Airdrop-PHRS/stPHRS/Delay Claim) и её сохранение на сервере.

Флоу для одного кошелька:
  1. curl_cffi (chrome131) + прокси (реюзаем ClaimChecker для auth).
  2. personal_sign → POST /accounts/sign_in_blockchain → token.
  3. GET  /airdrop/airdrop_info            (читаем текущий claim_tier)
  4. POST /airdrop/airdrop_info {tier:T}   ← сохраняет выбор
  5. (опц.) GET /airdrop/airdrop_info      (верификация)

Ответы API:
  success                    : {"success":true,"code":0,"data":{...}}
  адрес не eligible         : {"success":true,"code":40002,"message":"request failed","data":null}
  нет записи (код 40001)    : {"success":true,"code":40001,"message":"no data"}
"""
from __future__ import annotations

import random
import time
from typing import Callable, Optional

from config.modules.cfg_base import RETRY_COUNT, SLEEP_BETWEEN_ACTIONS
from config.modules.cfg_pharos_claim import (
    API_BASE_URL,
    CLAIM_REQUEST_TIMEOUT,
    INFO_ENDPOINT,
    REGISTER_DEFAULT_TIER,
    REGISTER_VERIFY_AFTER,
    UPDATE_TIER_ENDPOINT,
)
from modules.pharos_claim.checker import ClaimChecker
from modules.simple_logger import logger as _logger

_VALID_TIERS = ("now", "30days", "60days", "90days", "stake")


class RegisterActionResult:
    """Результат одной попытки зарегистрировать tier."""

    __slots__ = (
        "ok",
        "tier",
        "saved_tier",
        "already_registered",
        "not_eligible",
        "error",
        "raw_response",
    )

    def __init__(
        self,
        *,
        ok: bool = False,
        tier: Optional[str] = None,
        saved_tier: Optional[str] = None,
        already_registered: bool = False,
        not_eligible: bool = False,
        error: Optional[str] = None,
        raw_response: Optional[dict] = None,
    ) -> None:
        self.ok = ok
        self.tier = tier
        self.saved_tier = saved_tier
        self.already_registered = already_registered
        self.not_eligible = not_eligible
        self.error = error
        self.raw_response = raw_response


def _short(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}"


# ─────────────────── клиент ───────────────────

class TierRegistrar:
    """Одна curl_cffi-сессия = один кошелёк = одна регистрация."""

    def __init__(self, private_key: str, proxy: Optional[str]) -> None:
        # Переиспользуем всю низкоуровневую логику (подпись, warmup,
        # authenticate, fetch_airdrop_info) из ClaimChecker.
        self._checker = ClaimChecker(private_key, proxy)
        self.address: str = self._checker.address
        self.proxy: Optional[str] = proxy

    def close(self) -> None:
        self._checker.close()

    # ───────── POST update tier ─────────
    def _post_tier(self, token: str, tier: str) -> tuple[Optional[dict], Optional[str]]:
        url = API_BASE_URL + UPDATE_TIER_ENDPOINT
        try:
            resp = self._checker._session.post(
                url,
                json={"tier": tier},
                headers={
                    "Authorization": f"TOKEN {token}",
                    "Content-Type": "application/json",
                },
                timeout=CLAIM_REQUEST_TIMEOUT,
            )
        except Exception as e:
            return None, f"update_tier request failed: {type(e).__name__}: {str(e)[:160]}"

        preview = (resp.text or "")[:200].replace("\n", " ")
        if resp.status_code != 200:
            return None, f"update_tier HTTP {resp.status_code}: {preview}"
        try:
            return resp.json(), None
        except Exception as e:
            return None, f"update_tier json parse: {e} | {preview}"

    # ───────── главный метод ─────────
    def register(self, tier: str = REGISTER_DEFAULT_TIER) -> RegisterActionResult:
        tier = (tier or REGISTER_DEFAULT_TIER).strip()
        if tier not in _VALID_TIERS:
            return RegisterActionResult(
                ok=False,
                tier=tier,
                error=f"invalid tier '{tier}', allowed: {','.join(_VALID_TIERS)}",
            )

        # warmup + auth (reuse)
        self._checker.warmup()
        time.sleep(random.uniform(0.2, 0.8))

        token, err = self._checker.authenticate()
        if err or not token:
            return RegisterActionResult(ok=False, tier=tier, error=err or "auth failed")

        # Сначала GET: проверим, что адрес eligible и узнаем текущий tier.
        info_body, info_err = self._checker.fetch_airdrop_info(token)
        current_tier: Optional[str] = None
        if not info_err and isinstance(info_body, dict):
            data = info_body.get("data") if isinstance(info_body, dict) else None
            code = info_body.get("code")
            # 40001 = "no data" → адрес вообще не в раздаче.
            if code == 40001 or (code == 0 and data is None):
                return RegisterActionResult(
                    ok=False,
                    tier=tier,
                    not_eligible=True,
                    error="not eligible (api code=40001 'no data')",
                    raw_response=info_body,
                )
            if isinstance(data, dict):
                t = data.get("claim_tier")
                if isinstance(t, str) and t.strip():
                    current_tier = t.strip()

        if current_tier == tier:
            # Уже зарегистрирован в нужной опции — идемпотентно выходим.
            return RegisterActionResult(
                ok=True,
                tier=tier,
                saved_tier=current_tier,
                already_registered=True,
                raw_response=info_body,
            )

        # POST update.
        time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
        resp_body, post_err = self._post_tier(token, tier)
        if post_err:
            return RegisterActionResult(ok=False, tier=tier, error=post_err)

        code = resp_body.get("code") if isinstance(resp_body, dict) else None
        msg = resp_body.get("message") if isinstance(resp_body, dict) else None

        # Сервер возвращает 40002 "request failed" для не-eligible кошельков.
        if code == 40002:
            return RegisterActionResult(
                ok=False,
                tier=tier,
                not_eligible=True,
                error=f"api rejected: code={code}, message={msg!r}",
                raw_response=resp_body,
            )
        if code not in (0, None):
            return RegisterActionResult(
                ok=False,
                tier=tier,
                error=f"api error: code={code}, message={msg!r}",
                raw_response=resp_body,
            )

        saved_tier = tier
        if REGISTER_VERIFY_AFTER:
            time.sleep(random.uniform(0.3, 1.0))
            verify_body, verify_err = self._checker.fetch_airdrop_info(token)
            if not verify_err and isinstance(verify_body, dict):
                vdata = verify_body.get("data")
                if isinstance(vdata, dict):
                    vt = vdata.get("claim_tier")
                    if isinstance(vt, str) and vt.strip():
                        saved_tier = vt.strip()
                if saved_tier != tier:
                    return RegisterActionResult(
                        ok=False,
                        tier=tier,
                        saved_tier=saved_tier,
                        error=f"verify mismatch: expected {tier!r}, got {saved_tier!r}",
                        raw_response=verify_body,
                    )

        return RegisterActionResult(
            ok=True,
            tier=tier,
            saved_tier=saved_tier,
            already_registered=False,
            raw_response=resp_body,
        )


# ─────────────────── public helper with retry ───────────────────

def register_wallet_with_retry(
    private_key: str,
    proxy: Optional[str],
    *,
    tier: str = REGISTER_DEFAULT_TIER,
    on_proxy_rotate: Optional[Callable[[], Optional[str]]] = None,
) -> RegisterActionResult:
    """Зарегистрировать выбранный tier с несколькими попытками и ротацией прокси.

    Терминальные ошибки (не eligible, invalid tier) прерывают ретраи.
    """
    last_err = "unknown"
    current_proxy = proxy

    for attempt in range(1, RETRY_COUNT + 1):
        reg = TierRegistrar(private_key, current_proxy)
        try:
            result = reg.register(tier)
        finally:
            reg.close()

        if result.ok:
            return result

        if result.not_eligible:
            # 40001/40002 — смысла ретраить нет.
            return result
        if result.error and "invalid tier" in result.error:
            return result

        last_err = result.error or "unknown"
        _logger.debug(
            f"[{_short(reg.address)}] register attempt {attempt}/{RETRY_COUNT} "
            f"proxy={current_proxy or 'direct'}: {last_err[:180]}"
        )

        if attempt < RETRY_COUNT:
            if on_proxy_rotate is not None:
                rotated = on_proxy_rotate()
                if rotated:
                    current_proxy = rotated
            time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

    return RegisterActionResult(ok=False, tier=tier, error=last_err)
