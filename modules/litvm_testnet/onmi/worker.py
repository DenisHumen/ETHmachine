"""Onmi — planner + executor.

Phase 1 (plan_wallet):
  • читаем native zkLTC баланс кошелька
  • если < ONMI_MIN_NATIVE_BALANCE_ZKLTC → skipped
  • генерируем coin metadata (name/symbol [+description в ~5% случаев])
  • рандомно решаем: createTokenAndBuy (default) или createToken
  • если createTokenAndBuy: выбираем initial_buy_wei из ONMI_INITIAL_BUY_RANGE_ZKLTC,
    проверяем что (initial_buy + gas_reserve) ≤ native_balance → иначе skipped
  • upsert task status='pending'

Phase 2 (process_wallet):
  1. (если ещё не сделано) image: скачиваем с Pinterest, ресайз
  2. POST /api/upload/image → image_uploaded_url
  3. POST /api/upload/metadata → metadata_uri
  4. on-chain: createTokenAndBuy / createToken
  5. парсим receipt → token_address, tokens_received_wei
  6. status='arrived'
"""
from __future__ import annotations

import random
import time
from typing import Optional

from config.modules.cfg_litvm_testnet import (
    ONMI_DESCRIPTION_PROBABILITY,
    ONMI_GAS_RESERVE_ZKLTC,
    ONMI_INITIAL_BUY_PROBABILITY,
    ONMI_INITIAL_BUY_RANGE_ZKLTC,
    ONMI_MIN_NATIVE_BALANCE_ZKLTC,
    ONMI_SLEEP_BETWEEN_TX,
    ONMI_TX_ATTEMPTS,
)
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.onmi import database as db
from modules.litvm_testnet.onmi import name_generator
from modules.litvm_testnet.onmi import onmi_client as oc
from modules.litvm_testnet.onmi import image_provider as ip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_tx(h: Optional[str]) -> str:
    if not h:
        return ""
    raw = h[2:] if h.startswith("0x") else h
    return f"{raw[:8]}…{raw[-6:]}" if len(raw) > 16 else raw


def _primary_proxy(record: dict) -> Optional[str]:
    p = (record.get("proxy") or "").strip()
    return p or None


def _reserve_proxy(record: dict) -> Optional[str]:
    p = (record.get("reserve_proxy") or "").strip()
    return p or None


def _proxy_chain(record: dict) -> list[Optional[str]]:
    chain: list[Optional[str]] = []
    seen: set[str] = set()
    for p in (_primary_proxy(record), _reserve_proxy(record)):
        key = (p or "").strip()
        if key in seen:
            continue
        chain.append(p)
        seen.add(key)
    if not chain:
        chain = [None]
    return chain


def _account_from_record(record: dict):
    pk = (record.get("private_key") or "").strip()
    if not pk:
        return None
    try:
        return oc.account_from_private_key(pk)
    except Exception as e:  # noqa: BLE001
        log_simple(f"⚠ невалидный private_key: {e}", "warning")
        return None


def _native_balance_with_fallback(address: str, record: dict
                                  ) -> tuple[int, Optional[str]]:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(record):
        try:
            return oc.get_native_balance_wei(address, proxy), proxy
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise oc.OnmiError(f"native balance fetch failed: {last_err}")


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------

def plan_wallet(record: dict, idx: int, total: int) -> bool:
    account = _account_from_record(record)
    if account is None:
        return False
    address = account.address
    account_name = record.get("name") or None

    try:
        native_wei, _ = _native_balance_with_fallback(address, record)
    except oc.OnmiError as e:
        log_wallet_task(address, idx, total,
                        f"⚠ balance fetch failed: {e}",
                        "warning", account_name=account_name)
        return False

    native_zkltc = native_wei / 1e18
    min_native = float(ONMI_MIN_NATIVE_BALANCE_ZKLTC)
    if native_zkltc < min_native:
        # запишем skipped с пустыми coin_name/symbol (NOT NULL constraint требует строку)
        db.upsert_task(
            address=address, name=account_name, tx_index=1,
            coin_name="-", coin_symbol="-", coin_description=None,
            initial_buy_wei=0, initial_buy_human=0.0,
            native_balance_before_wei=native_wei,
            status="skipped",
        )
        log_wallet_task(address, idx, total,
                        f"⏭ skip · native {native_zkltc:.5f} < min {min_native}",
                        "warning", account_name=account_name)
        return False

    # Решаем: createTokenAndBuy (с initial buy) или просто createToken
    do_initial_buy = random.random() < float(ONMI_INITIAL_BUY_PROBABILITY)
    initial_buy_wei = 0
    initial_buy_human = 0.0
    gas_reserve_wei = int(float(ONMI_GAS_RESERVE_ZKLTC) * 1e18)

    if do_initial_buy:
        lo, hi = ONMI_INITIAL_BUY_RANGE_ZKLTC
        amt = random.uniform(float(lo), float(hi))
        initial_buy_wei = int(amt * 1e18)
        # Проверка: хватит ли на initial_buy + gas reserve
        if initial_buy_wei + gas_reserve_wei > native_wei:
            # уменьшаем до влезающего
            initial_buy_wei = max(0, native_wei - gas_reserve_wei)
            if initial_buy_wei < int(float(lo) * 1e18 * 0.5):
                # слишком мало → откатываемся на createToken (без buy)
                initial_buy_wei = 0
        initial_buy_human = initial_buy_wei / 1e18

    # Генерим метаданные
    meta = name_generator.generate_coin_metadata(
        used_symbols=db.used_symbols(),
        description_probability=float(ONMI_DESCRIPTION_PROBABILITY),
    )

    db.upsert_task(
        address=address, name=account_name, tx_index=1,
        coin_name=meta["name"], coin_symbol=meta["symbol"],
        coin_description=meta.get("description"),
        initial_buy_wei=initial_buy_wei, initial_buy_human=initial_buy_human,
        native_balance_before_wei=native_wei,
        status="pending",
    )
    mode = "createTokenAndBuy" if initial_buy_wei > 0 else "createToken"
    log_wallet_task(
        address, idx, total,
        f"📋 plan · {meta['name']} ({meta['symbol']}) · {mode}"
        + (f" · buy={initial_buy_human:.5f} zkLTC" if initial_buy_wei else "")
        + (" · +descr" if meta.get("description") else ""),
        "info", account_name=account_name,
    )
    return True


# ---------------------------------------------------------------------------
# Phase 2
# ---------------------------------------------------------------------------

def _upload_image_with_fallback(local_path, record: dict) -> str:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(record):
        try:
            return oc.upload_image(image_path=local_path, proxy=proxy)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise oc.OnmiError(f"image upload failed via all proxies: {last_err}")


def _upload_metadata_with_fallback(*, name, symbol, description, image_url,
                                   record: dict) -> str:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(record):
        try:
            return oc.upload_metadata(
                name=name, symbol=symbol, description=description or "",
                image_url=image_url, proxy=proxy,
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise oc.OnmiError(f"metadata upload failed: {last_err}")


def _send_tx_with_fallback(*, account, task: dict, record: dict
                           ) -> tuple[str, dict, Optional[str], int]:
    """Возвращает (tx_hash, receipt, token_address, tokens_received_wei)."""
    last_err: Optional[Exception] = None
    initial_buy_wei = int(task.get("initial_buy_wei") or 0)
    name = task["coin_name"]
    symbol = task["coin_symbol"]
    token_uri = task["metadata_uri"]

    for proxy in _proxy_chain(record):
        try:
            if initial_buy_wei > 0:
                return oc.send_create_token_and_buy(
                    account=account, name=name, symbol=symbol,
                    token_uri=token_uri, value_wei=initial_buy_wei,
                    proxy=proxy,
                )
            h, r, t = oc.send_create_token(
                account=account, name=name, symbol=symbol,
                token_uri=token_uri, proxy=proxy,
            )
            return h, r, t, 0
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise oc.OnmiError(f"tx send failed via all proxies: {last_err}")


def process_wallet(record: dict, idx: int, total: int) -> bool:
    account = _account_from_record(record)
    if account is None:
        return False
    address = account.address
    account_name = record.get("name") or None

    task = db.get_task_for_wallet(address, tx_index=1)
    if task is None or (task.get("status") or "").lower() == "skipped":
        if not plan_wallet(record, idx, total):
            return False
        task = db.get_task_for_wallet(address, tx_index=1)
        if task is None:
            return False

    status = (task.get("status") or "pending").lower()
    if status == "arrived":
        log_wallet_task(address, idx, total,
                        f"✅ уже создан ранее · {task.get('coin_name')} "
                        f"({task.get('coin_symbol')}) · "
                        f"token={task.get('token_address')}",
                        "info", account_name=account_name)
        return True
    if status == "skipped":
        return False
    if status not in ("pending", "image_ready", "metadata_ready",
                      "tx_sent", "failed"):
        log_wallet_task(address, idx, total,
                        f"⚠ unknown status='{status}' · пропуск",
                        "warning", account_name=account_name)
        return False

    task_id = int(task["id"])

    # --- Step 1: image -----------------------------------------------------
    image_uploaded_url = task.get("image_uploaded_url")
    image_local_path = task.get("image_local_path")
    image_source_url = task.get("image_source_url")
    if not image_uploaded_url:
        # либо локальный файл есть и просто не загружен, либо нужно скачать заново
        local_path = None
        if image_local_path:
            from pathlib import Path as _P
            p = _P(image_local_path)
            if p.exists():
                local_path = p
        if local_path is None:
            try:
                local_path, image_source_url = ip.fetch_and_prepare_image(
                    proxy=_primary_proxy(record),
                )
            except ip.ImageError as e:
                db.update_task(
                    task_id, status="failed",
                    error_message=f"image fetch: {str(e)[:300]}",
                )
                log_wallet_task(address, idx, total,
                                f"❌ image fetch failed: {e}",
                                "error", account_name=account_name)
                return False
            db.update_task(
                task_id,
                image_local_path=str(local_path),
                image_source_url=image_source_url or "",
            )
        # загружаем на onmi S3
        log_wallet_task(address, idx, total,
                        "📤 uploading image to onmi S3...",
                        "info", account_name=account_name)
        try:
            image_uploaded_url = _upload_image_with_fallback(local_path, record)
        except oc.OnmiError as e:
            db.update_task(
                task_id, status="failed",
                error_message=f"image upload: {str(e)[:300]}",
            )
            log_wallet_task(address, idx, total,
                            f"❌ image upload failed: {e}",
                            "error", account_name=account_name)
            return False
        db.update_task(
            task_id, image_uploaded_url=image_uploaded_url,
            status="image_ready", error_message=None,
        )

    # --- Step 2: metadata --------------------------------------------------
    metadata_uri = task.get("metadata_uri")
    if not metadata_uri:
        # после первой загрузки task в БД, перечитаем актуальный image_uploaded_url
        log_wallet_task(address, idx, total,
                        "📤 uploading metadata...",
                        "info", account_name=account_name)
        try:
            metadata_uri = _upload_metadata_with_fallback(
                name=task["coin_name"], symbol=task["coin_symbol"],
                description=task.get("coin_description") or "",
                image_url=image_uploaded_url,
                record=record,
            )
        except oc.OnmiError as e:
            db.update_task(
                task_id, status="failed",
                error_message=f"metadata upload: {str(e)[:300]}",
            )
            log_wallet_task(address, idx, total,
                            f"❌ metadata upload failed: {e}",
                            "error", account_name=account_name)
            return False
        db.update_task(
            task_id, metadata_uri=metadata_uri,
            status="metadata_ready", error_message=None,
        )

    # подгрузим свежий task для tx
    task = db.get_task_for_wallet(address, tx_index=1)
    if task is None:
        return False
    task_id = int(task["id"])

    # --- Step 3: on-chain --------------------------------------------------
    initial_buy_wei = int(task.get("initial_buy_wei") or 0)
    mode = "createTokenAndBuy" if initial_buy_wei > 0 else "createToken"
    log_wallet_task(
        address, idx, total,
        f"📤 {mode} · {task['coin_name']} ({task['coin_symbol']})"
        + (f" · buy={initial_buy_wei/1e18:.5f} zkLTC" if initial_buy_wei else ""),
        "info", account_name=account_name,
    )

    attempts = max(1, int(ONMI_TX_ATTEMPTS))
    last_err: Optional[str] = None
    tx_hash: Optional[str] = None
    receipt: Optional[dict] = None
    token_address: Optional[str] = None
    tokens_received = 0
    for attempt in range(1, attempts + 1):
        db.update_task(
            task_id, status="tx_sent",
            attempts=int(task.get("attempts") or 0) + attempt,
            sent_at=time.time(),
        )
        try:
            tx_hash, receipt, token_address, tokens_received = (
                _send_tx_with_fallback(account=account, task=task, record=record)
            )
            break
        except oc.OnmiError as e:
            last_err = str(e)
            log_wallet_task(
                address, idx, total,
                f"⚠ attempt {attempt}/{attempts}: {e}",
                "warning", account_name=account_name,
            )
            if attempt < attempts:
                time.sleep(min(15, 3 * attempt))
            continue

    if tx_hash is None or receipt is None:
        db.update_task(
            task_id, status="failed",
            error_message=(last_err or "unknown")[:500],
        )
        log_wallet_task(
            address, idx, total,
            f"❌ {mode} failed после {attempts} попыток: {last_err}",
            "error", account_name=account_name,
        )
        return False

    gas_used = int(receipt.get("gasUsed") or 0)
    db.update_task(
        task_id,
        tx_hash=tx_hash,
        gas_used=gas_used,
        token_address=token_address or "",
        tokens_received_wei=str(int(tokens_received)),
        status="arrived",
        error_message=None,
        confirmed_at=time.time(),
    )
    # регистрируем токен в реестре trade-модуля (persistent, не удаляется при reset).
    if token_address:
        try:
            from modules.litvm_testnet.onmi.trade import database as _trade_db
            _trade_db.register_token(
                address=token_address,
                symbol=task.get("coin_symbol") or "",
                name=task.get("coin_name") or "",
                creator_address=address,
                source="coin_module",
            )
        except Exception:
            pass
    log_wallet_task(
        address, idx, total,
        f"✅ {mode} · tx={_short_tx(tx_hash)} · gas={gas_used}"
        + (f" · token={token_address}" if token_address else " · ⚠ token_address не извлечён из логов")
        + (f" · received={tokens_received/1e18:.4f}" if tokens_received else ""),
        "success", account_name=account_name,
    )

    # пауза, чтобы не флудить RPC при многопоточке
    lo, hi = ONMI_SLEEP_BETWEEN_TX
    time.sleep(random.uniform(float(lo), float(hi)))
    return True
