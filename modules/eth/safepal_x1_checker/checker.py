"""Чекер одного кошелька + многопоточный раннер."""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from eth_account import Account
from openpyxl import Workbook

from config.modules.cfg_safepal_x1_checker import ACT_CODE, CHAIN_ID, CHANNEL_CODE
from config.modules.general_config import (
    NUM_THREADS as _CFG_NUM_THREADS,
    RETRY_COUNT,
    SLEEP_BETWEEN_ACTIONS,
)
from modules.data_manager import load_data
from modules.eth.safepal_x1_checker.database import (
    DB_PATH,
    create_tasks,
    get_all_results,
    get_pending_addresses,
    get_task_statistics,
    init_database,
    update_task_failed,
    update_task_success,
)
from modules.eth.safepal_x1_checker.safepal_api import (
    SafepalError,
    auth_sign,
    check_channel_code,
    check_is_can_order,
    get_activity_shopping_token,
    get_sign_msg,
    sign_personal_message,
)
from modules.proxy_manager import get_proxy_dict, mask_proxy
from modules.simple_logger import log_simple, log_wallet_task, logger, set_auto_progress

_NUM_THREADS = max(1, int(_CFG_NUM_THREADS))
_RETRY = max(1, int(RETRY_COUNT))
_SLEEP_RANGE = SLEEP_BETWEEN_ACTIONS if isinstance(SLEEP_BETWEEN_ACTIONS, (list, tuple)) and len(SLEEP_BETWEEN_ACTIONS) == 2 else [1, 2]


# ──────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────

def _addr_from_pk(pk: str) -> str:
    return Account.from_key(pk).address


def _build_records() -> List[Dict[str, str]]:
    """Из CSV → [{address, account_name, private_key, proxy, reserve_proxy}]."""
    rows = load_data()
    out: List[Dict[str, str]] = []
    for r in rows:
        pk = (r.get("private_key") or "").strip()
        if not pk:
            continue
        try:
            addr = _addr_from_pk(pk)
        except Exception as exc:
            logger.warning(f"Пропуск {r.get('name', '')}: неверный private_key ({exc})")
            continue
        out.append({
            "wallet_address": addr,
            "account_name": r.get("name", ""),
            "private_key": pk,
            "proxy": (r.get("proxy") or "").strip(),
            "reserve_proxy": (r.get("reserve_proxy") or "").strip(),
        })
    return out


def _proxies_for(rec: Dict[str, str]) -> List[Optional[Dict[str, str]]]:
    """Возвращает список прокси-словарей для попыток: [main, reserve, None]."""
    seen: List[Optional[Dict[str, str]]] = []
    for raw in (rec.get("proxy"), rec.get("reserve_proxy")):
        d = get_proxy_dict(raw) if raw else None
        if d and d not in seen:
            seen.append(d)
    seen.append(None)  # direct fallback
    return seen


def _sleep_random() -> None:
    lo, hi = float(_SLEEP_RANGE[0]), float(_SLEEP_RANGE[1])
    if hi <= 0:
        return
    time.sleep(random.uniform(min(lo, hi), max(lo, hi)))


# ──────────────────────────────────────────────────────────────────────
# single-wallet flow
# ──────────────────────────────────────────────────────────────────────

def check_one_wallet(rec: Dict[str, str], idx: int, total: int,
                     act_code: str, channel_code: str, chain_id: Any,
                     channel_name_hint: Optional[str] = None,
                     sku_hint: Optional[str] = None) -> None:
    addr = rec["wallet_address"]
    name = rec.get("account_name", "")
    pk = rec["private_key"]

    proxies_list = _proxies_for(rec)
    last_error: Optional[Exception] = None

    for attempt in range(1, _RETRY + 1):
        proxy = proxies_list[(attempt - 1) % len(proxies_list)]
        try:
            log_wallet_task(addr, idx, total,
                            f"🔐 запрос сообщения для подписи (chain={chain_id}, proxy={mask_proxy(_first_proxy_string(proxy))})",
                            "info", account_name=name)
            sign_msg = get_sign_msg(chain_id, addr, proxies=proxy)
            msg = sign_msg["msg"]
            nonce = sign_msg["nonce"]
            server_time = sign_msg["serverTime"]

            signature = sign_personal_message(pk, msg)

            log_wallet_task(addr, idx, total, "✍️ отправка подписи (authSign)",
                            "info", account_name=name)
            auth = auth_sign(chain_id, addr, signature, server_time, msg, nonce, proxies=proxy)
            session_id = auth["session_id"]

            log_wallet_task(addr, idx, total, "📤 получение activity token",
                            "info", account_name=name)
            token = get_activity_shopping_token(chain_id, addr, act_code, channel_code,
                                                session_id, proxies=proxy)

            log_wallet_task(addr, idx, total, "🔍 checkIsCanOrder",
                            "info", account_name=name)
            result = check_is_can_order(token, chain_id, addr, session_id, proxies=proxy)

            eligible = result.strip().upper() == "YES"
            level = "success" if eligible else "warning"
            icon = "✅" if eligible else "❌"
            log_wallet_task(addr, idx, total,
                            f"{icon} результат: {result} (eligible={eligible})",
                            level, account_name=name)
            update_task_success(addr, eligible, result, channel_name_hint, sku_hint, session_id)
            return

        except SafepalError as exc:
            last_error = exc
            log_wallet_task(addr, idx, total,
                            f"⚠ попытка {attempt}/{_RETRY}: {exc}",
                            "warning", account_name=name)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log_wallet_task(addr, idx, total,
                            f"⚠ попытка {attempt}/{_RETRY}: {type(exc).__name__}: {exc}",
                            "warning", account_name=name)

        _sleep_random()

    # все попытки исчерпаны
    msg = f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error"
    log_wallet_task(addr, idx, total, f"❌ failed: {msg}", "error", account_name=name)
    update_task_failed(addr, msg)


def _first_proxy_string(proxy_dict: Optional[Dict[str, str]]) -> Optional[str]:
    if not proxy_dict:
        return None
    return proxy_dict.get("https") or proxy_dict.get("http")


# ──────────────────────────────────────────────────────────────────────
# orchestration
# ──────────────────────────────────────────────────────────────────────

def run_checker() -> None:
    """Основной запуск: phase-1 build tasks → phase-2 параллельный чекер."""
    set_auto_progress(False)
    init_database()

    records = _build_records()
    if not records:
        log_simple("Нет валидных кошельков в data.csv (нужно поле private_key).", "warning")
        return

    # Phase 1: подготовка задач
    log_simple(f"📋 загружено кошельков: {len(records)}", "info")
    create_tasks(
        [{"wallet_address": r["wallet_address"], "account_name": r["account_name"]} for r in records],
        ACT_CODE, CHANNEL_CODE, CHAIN_ID,
    )

    # checkChannelCode 1 раз — узнаём channelName/sku
    channel_name = None
    sku = None
    try:
        log_simple(f"📡 checkChannelCode: actCode={ACT_CODE} channelCode={CHANNEL_CODE}", "info")
        meta = check_channel_code(ACT_CODE, CHANNEL_CODE)
        channel_name = meta.get("channelName")
        sku = meta.get("sku")
        log_simple(f"   channelName={channel_name} sku={sku} chainType={meta.get('chainType')}", "info")
    except SafepalError as exc:
        log_simple(f"⚠ checkChannelCode failed: {exc} (продолжаем без metadata)", "warning")

    # Phase 2: фильтруем только pending/failed
    pending_addrs = set(get_pending_addresses())
    todo = [r for r in records if r["wallet_address"] in pending_addrs]
    if not todo:
        log_simple("✅ все кошельки уже проверены, нечего делать.", "success")
        return

    total = len(todo)
    threads = max(1, min(_NUM_THREADS, total))
    log_simple(f"▶️ запуск чекера: задач={total}, потоков={threads}", "info")

    stop_flag = {"stop": False}

    def _worker(i: int, rec: Dict[str, str]) -> None:
        if stop_flag["stop"]:
            return
        check_one_wallet(rec, i, total, ACT_CODE, CHANNEL_CODE, CHAIN_ID,
                         channel_name_hint=channel_name, sku_hint=sku)

    if threads <= 1:
        try:
            for i, rec in enumerate(todo, 1):
                _worker(i, rec)
        except KeyboardInterrupt:
            log_simple("⛔ прервано пользователем (состояние сохранено в БД).", "warning")
            return
    else:
        with ThreadPoolExecutor(max_workers=threads, thread_name_prefix="safepal_x1") as ex:
            futs = [ex.submit(_worker, i, rec) for i, rec in enumerate(todo, 1)]
            try:
                for fut in as_completed(futs):
                    fut.result()
            except KeyboardInterrupt:
                stop_flag["stop"] = True
                for f in futs:
                    f.cancel()
                log_simple("⛔ прервано пользователем (состояние сохранено в БД).", "warning")
                return

    # финальная статистика
    s = get_task_statistics()
    log_simple(
        f"📊 итог: total={s['total']} ok={s['completed']} pending={s['pending']} failed={s['failed']} "
        f"eligible={s['eligible']} not_eligible={s['not_eligible']}",
        "success",
    )


# ──────────────────────────────────────────────────────────────────────
# Excel export
# ──────────────────────────────────────────────────────────────────────

def export_results_xlsx() -> Optional[Path]:
    rows = get_all_results()
    if not rows:
        return None
    out_dir = Path(__file__).resolve().parents[3] / "result" / "safepal_x1_checker"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"safepal_x1_checker_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Tasks"
    headers = list(rows[0].keys())
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h) for h in headers])

    summary = wb.create_sheet("Summary")
    s = get_task_statistics()
    for k, v in s.items():
        summary.append([k, v])

    wb.save(out_path)
    return out_path


def print_run_statistics() -> None:
    s = get_task_statistics()
    log_simple(
        f"total={s['total']} completed={s['completed']} pending={s['pending']} "
        f"failed={s['failed']} eligible={s['eligible']} not_eligible={s['not_eligible']}",
        "info",
    )
