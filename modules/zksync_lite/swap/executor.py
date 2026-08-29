"""Executor: исполняет задачи свопа из swap_tasks по одному кошельку.

Стратегия per wallet (sequential, чтобы не ломать nonce):
  1. account-info; если !isActive → change-pubkey (комиссия ETH).
  2. По очереди (priority asc) задачи:
       layerswap        → create swap → Lite transfer на deposit_address →
                          poll Layerswap до COMPLETED + сверка Era баланса.
       manual_withdraw  → Lite withdraw в L1 на свой же ETH-адрес. Дальше
                          бридж L1→Era — вручную (статус: withdrawn).
  3. При фатальной ошибке: красный баннер с пояснением, прерывание остальных
     задач этого кошелька.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests

from modules.simple_logger import logger
from modules.zksync_lite.swap import swap_database as swap_db
from modules.zksync_lite.swap.era_verifier import EraVerifier
from modules.zksync_lite.swap.layerswap_client import (
    LayerswapClient, LayerswapError, SUPPORTED_PAIRS,
)
from modules.zksync_lite.swap.lite_signer import LiteSigner, LiteSignerError

ARRIVAL_TIMEOUT_SEC = 20 * 60     # 20 минут
ARRIVAL_POLL_INTERVAL = 15
LAYERSWAP_POLL_INTERVAL = 15

BANNER_LINE = "═" * 78

# Сетевые исключения, после которых стоит переключиться на резервную прокси.
_NET_EXC = (
    requests.exceptions.ProxyError,
    requests.exceptions.ConnectionError,
    requests.exceptions.SSLError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _is_net_error(exc: BaseException) -> bool:
    """True, если исключение похоже на проблему с сетью/прокси."""
    if isinstance(exc, _NET_EXC):
        return True
    msg = (str(exc) or "").lower()
    return ("proxy" in msg or "max retries" in msg or "connection" in msg
            or "timed out" in msg)


def _print_banner(title: str, lines: List[str], symbol: str = "!") -> None:
    print(f"\n{BANNER_LINE}")
    print(f" {symbol*3} {title} {symbol*3}")
    print(BANNER_LINE)
    for ln in lines:
        print(f"  {ln}")
    print(BANNER_LINE + "\n")


def _format_proxies(proxy: Optional[str]) -> Optional[Dict[str, str]]:
    if not proxy:
        return None
    p = proxy.strip()
    if not p:
        return None
    if "://" not in p:
        p = "http://" + p
    return {"http": p, "https": p}


class ProxyPool:
    """Хранит primary + reserve прокси и переключается на reserve при сбое."""

    def __init__(self, primary: Optional[str], reserve: Optional[str],
                 *, label: str = "") -> None:
        self._primary = _format_proxies(primary)
        self._reserve = _format_proxies(reserve)
        self._current_kind = "primary" if self._primary else (
            "reserve" if self._reserve else "none"
        )
        self._label = label

    @property
    def current(self) -> Optional[Dict[str, str]]:
        if self._current_kind == "primary":
            return self._primary
        if self._current_kind == "reserve":
            return self._reserve
        return None

    @property
    def kind(self) -> str:
        return self._current_kind

    def has_reserve(self) -> bool:
        return self._reserve is not None and self._current_kind != "reserve"

    def switch_to_reserve(self, reason: str = "") -> bool:
        """Переключение primary→reserve. Возвращает True если переключилось."""
        if self._reserve is None or self._current_kind == "reserve":
            return False
        logger.warning(f"{self._label}переключаемся на резервную прокси "
                       f"(причина: {reason[:160]})")
        self._current_kind = "reserve"
        return True


def _retry_with_pool(pool: ProxyPool, fn, *, max_attempts: int = 3,
                     backoff: float = 2.0):
    """Запускает fn(proxies=...) с переключением proxy при сетевых ошибках.

    fn принимает kwarg `proxies` и возвращает результат либо бросает.
    На LayerswapError (это уже валидная ошибка API) — НЕ ретраим.
    На сетевой — переключаемся на резерв (один раз) и повторяем.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(proxies=pool.current)
        except LayerswapError:
            raise
        except Exception as exc:
            last_exc = exc
            if not _is_net_error(exc):
                raise
            logger.warning(f"net error attempt {attempt}/{max_attempts}: {exc}")
            switched = pool.switch_to_reserve(str(exc))
            if not switched and attempt >= max_attempts:
                break
            time.sleep(backoff * attempt)
    raise last_exc  # type: ignore[misc]


class SwapExecutor:
    def __init__(self, *, signer: Optional[LiteSigner] = None,
                 layerswap: Optional[LayerswapClient] = None,
                 era: Optional[EraVerifier] = None,
                 stop_on_failure: bool = False) -> None:
        self.signer = signer or LiteSigner()
        self.layerswap = layerswap or LayerswapClient()
        self.era = era or EraVerifier()
        self.stop_on_failure = stop_on_failure
        # сюда складываем фейлы для финального summary
        self.failures: List[Dict[str, Any]] = []

    # ───────── orchestration ─────────

    def run_all(self) -> Dict[str, Any]:
        wallets = swap_db.list_wallets_with_pending()
        logger.info(f"кошельков с pending-задачами: {len(wallets)}")
        results: Dict[str, str] = {}
        for i, wallet in enumerate(wallets, 1):
            print(f"\n[{i}/{len(wallets)}] {wallet}")
            try:
                self.run_wallet(wallet)
                results[wallet] = "ok"
            except Exception as exc:
                logger.exception(f"необработанная ошибка по кошельку {wallet}")
                results[wallet] = f"error: {exc}"
                _print_banner(
                    "ОШИБКА КОШЕЛЬКА (продолжаем со следующего)",
                    [f"wallet: {wallet}", f"reason: {exc}"],
                    symbol="!",
                )
        return {"results": results, "stats": swap_db.get_statistics(),
                "failures": self.failures}

    def run_wallet(self, wallet_address: str) -> None:
        tasks = swap_db.list_pending_for_wallet(wallet_address)
        if not tasks:
            return
        priv = tasks[0]["private_key"]
        proxy = tasks[0].get("proxy")
        # reserve_proxy лежит в extra_json первой задачи
        reserve_proxy = ""
        try:
            extra = json.loads(tasks[0].get("extra_json") or "{}")
            reserve_proxy = (extra or {}).get("reserve_proxy") or ""
        except Exception:
            pass
        pool = ProxyPool(proxy, reserve_proxy,
                         label=f"[{wallet_address}] ")
        # Прокси покрывает ТОЛЬКО HTTP-вызовы Layerswap. Транзакции zkSync Lite
        # идут через node-хелпер (signer.js), который прокси не поддерживает, —
        # поэтому не пишем в лог «прокси активна» без уточнения: пользователь
        # должен знать, что часть трафика уходит с реального IP.
        if not pool.current:
            logger.warning(f"[{wallet_address}] прокси не указана — идём напрямую")
        elif pool.has_reserve():
            logger.info(f"[{wallet_address}] прокси (только Layerswap API): "
                        f"primary активна, резерв в наличии")
        else:
            logger.info(f"[{wallet_address}] прокси (только Layerswap API): "
                        f"primary активна (без резерва)")
        if pool.current:
            logger.warning(f"[{wallet_address}] запросы zkSync Lite идут напрямую: "
                           f"node-хелпер не поддерживает прокси")

        # 1. account-info + ChangePubKey
        info = self.signer.account_info(priv)
        actual_addr = (info.get("address") or "").lower()
        if actual_addr != wallet_address.lower():
            raise RuntimeError(f"private_key выводит {actual_addr}, ожидался {wallet_address}")

        if not info.get("isActive"):
            logger.info(f"{wallet_address}: ChangePubKey требуется, отправляем")
            try:
                cpk = self.signer.change_pubkey(priv, fee_token="ETH")
                logger.info(f"ChangePubKey tx: {cpk.get('txHash')}")
            except LiteSignerError as e:
                self._fail_all_remaining(tasks, f"ChangePubKey failed: {e}")
                _print_banner("ChangePubKey не удался", [
                    f"wallet: {wallet_address}", f"reason: {e}",
                    "Дальнейшие задачи по кошельку пропущены."], symbol="!")
                return

        for task in tasks:
            try:
                self._run_task(task, pool)
            except Exception as exc:
                logger.exception(f"task {task['id']} failed")
                swap_db.update_task(
                    task["id"],
                    status=swap_db.STATUS_FAILED,
                    error_message=str(exc)[:500],
                )
                self.failures.append({
                    "task_id": task["id"], "wallet": task["wallet_address"],
                    "token": task["source_token"], "route": task["route"],
                    "error": str(exc),
                })
                _print_banner("ЗАДАЧА ПРОВАЛЕНА", [
                    f"wallet: {task['wallet_address']}",
                    f"token:  {task['source_token']}  amount: {task['amount_human_planned']}",
                    f"route:  {task['route']}",
                    f"swap_id: {task.get('layerswap_swap_id')}",
                    f"deposit_address: {task.get('deposit_address')}",
                    f"lite_tx: {task.get('lite_tx_hash')}",
                    f"reason: {exc}",
                ], symbol="!")
                if self.stop_on_failure:
                    self._fail_all_remaining(
                        [t for t in tasks if t["id"] != task["id"]
                         and t.get("status") == swap_db.STATUS_PENDING],
                        f"halted after task {task['id']} failure",
                    )
                    return

    # ───────── single task ─────────

    def _run_task(self, task: Dict[str, Any], pool: ProxyPool) -> None:
        route = task["route"]
        token = task["source_token"]
        wallet = task["wallet_address"]
        amount_raw = task["amount_raw_planned"]
        amount_human = Decimal(task["amount_human_planned"])
        priv = task["private_key"]

        swap_db.increment_attempts(task["id"])

        if route == "unsupported":
            swap_db.update_task(
                task["id"], status=swap_db.STATUS_SKIPPED,
                error_message=f"Layerswap не поддерживает {token} как source-токен из zkSync Lite",
            )
            logger.warning(f"[{wallet}] {token}: маршрут не поддерживается — пропуск")
            return
        if route == "layerswap":
            self._run_layerswap_task(task, pool, priv, wallet, token,
                                      amount_raw, amount_human)
        else:
            raise RuntimeError(f"unknown route: {route}")

    def _run_layerswap_task(self, task, pool: ProxyPool, priv, wallet, token,
                             amount_raw, amount_human) -> None:
        if token not in SUPPORTED_PAIRS:
            raise RuntimeError(f"Layerswap не поддерживает токен {token}")

        decimals = int(task["decimals"])
        scale = Decimal(10) ** decimals
        target_token = (task.get("target_token") or SUPPORTED_PAIRS[token]).strip()

        # Идемпотентность (AGENTS §14.3). Ctrl-C или обрыв сети во время
        # 20-минутного ожидания оставляют задачу в awaiting_arrival, и
        # `list_pending_for_wallet` вернёт её следующему запуску. Но Lite-перевод
        # на deposit_address уже сделан: баланс на Lite нулевой, и проверка
        # «реальный баланс = 0» ниже пометила бы задачу терминальным skipped —
        # деньги в мосте стали бы невидимыми. Если кошелёк успели пополнить,
        # то ушёл бы второй перевод. Поэтому при наличии tx только дожидаемся.
        prior_tx = (task.get("lite_tx_hash") or "").strip()
        prior_swap = (task.get("layerswap_swap_id") or "").strip()
        if prior_tx:
            if not prior_swap:
                raise RuntimeError(
                    f"Lite-перевод {prior_tx} отправлен, но swap_id не сохранён — "
                    f"повторно не отправляем, проверьте перевод вручную")
            logger.info(f"[{wallet}] {token}: Lite tx {prior_tx} уже отправлен — "
                        f"возобновляем ожидание прибытия (swap {prior_swap})")
            self._await_arrival(task, pool, wallet, prior_swap, target_token)
            return

        # 1) Чекнём реальный баланс на Lite — данные в balance-БД могут быть устаревшими.
        try:
            info = self.signer.account_info(priv)
            real_bal_raw = int((info.get("balances") or {}).get(token, "0") or "0")
        except LiteSignerError as e:
            raise RuntimeError(f"не удалось получить Lite баланс: {e}")
        if real_bal_raw <= 0:
            swap_db.update_task(
                task["id"], status=swap_db.STATUS_SKIPPED,
                error_message=f"реальный баланс {token}=0 на Lite",
            )
            logger.info(f"[{wallet}] {token}: баланс на Lite пустой — пропуск")
            return

        # 2) Идём от РЕАЛЬНОГО баланса (для drain под ноль).
        # Планируемая сумма из task используется только как верхняя граница
        # на случай ручного теста, где явно ограничили amount.
        planned_raw = int(amount_raw)
        send_raw = real_bal_raw
        if planned_raw > 0 and planned_raw < real_bal_raw:
            # план меньше реального только если пользователь явно сузил
            # (test_single_swap), либо balance-DB опередил наш план.
            # В обычном auto-плане planner ставит amount~=balance-reserve
            # и реальный баланс почти всегда совпадает или чуть больше.
            # Берём максимум — это и есть drain.
            send_raw = real_bal_raw

        # 2b) Подтягиваем актуальные лимиты Layerswap и применяем min/max.
        try:
            lim = _retry_with_pool(
                pool, lambda proxies: self.layerswap.limits(token, proxies=proxies),
            )
        except Exception as exc:
            logger.warning(f"[{wallet}] {token}: limits недоступны ({exc}), идём как есть")
            lim = None
        if lim:
            min_raw = int((lim["min_amount"] * scale).to_integral_value())
            max_raw = int((lim["max_amount"] * scale).to_integral_value())
            if max_raw > 0 and send_raw > max_raw:
                logger.info(f"[{wallet}] {token}: сумма {send_raw} превышает Layerswap max "
                            f"{max_raw} — обрезаем до max")
                send_raw = max_raw
            if min_raw > 0 and send_raw < min_raw:
                swap_db.update_task(
                    task["id"], status=swap_db.STATUS_SKIPPED,
                    error_message=(f"баланс {Decimal(send_raw)/scale} {token} ниже Layerswap "
                                   f"min={lim['min_amount']}"),
                )
                logger.info(f"[{wallet}] {token}: ниже Layerswap min — пропуск")
                return

        # 3) Выбираем feeToken: для ETH свопа — ETH; для стейбла — сам стейбл
        # (работает на кошельках без ETH).
        fee_token = "ETH" if token == "ETH" else token

        # 4) Предварительный quote для проверки экономической целесообразности.
        # send_human — ввод в Layerswap (без учёта Lite-fee на этом этапе).
        send_human = (Decimal(send_raw) / scale)

        # 5) Запрашиваем Lite-комиссию (фиксируется после create_swap, ибо
        #     для fee нужен реальный to-адрес deposit).
        # 6) Пред-quote на полную сумму (даёт понимание лимитов).
        try:
            q = _retry_with_pool(
                pool,
                lambda proxies: self.layerswap.quote(token, send_human, proxies=proxies),
            )
            qd = q.get("data") if isinstance(q, dict) else None
            if isinstance(qd, dict):
                rcv = qd.get("receive_amount") or qd.get("min_receive_amount")
                if rcv is not None and Decimal(str(rcv)) <= 0:
                    swap_db.update_task(
                        task["id"], status=swap_db.STATUS_SKIPPED,
                        error_message=f"layerswap quote: receive={rcv} ≤ 0",
                    )
                    logger.info(f"[{wallet}] {token}: пропущен (сумма ниже fee)")
                    return
        except LayerswapError as e:
            swap_db.update_task(
                task["id"], status=swap_db.STATUS_SKIPPED,
                error_message=f"layerswap quote: {e}"[:500],
            )
            logger.warning(f"[{wallet}] {token}: quote недоступен — пропуск ({e})")
            return

        # baseline баланс на Era (по target_token, не source!)
        try:
            era_before = self.era.get_balance_raw(wallet, target_token)
        except Exception as exc:
            logger.warning(f"Era baseline read failed: {exc}; продолжаем без сверки")
            era_before = None
        swap_db.update_task(task["id"],
                            era_balance_before=str(era_before) if era_before is not None else None)

        # 7) Layerswap create_swap с реальной суммой
        swap = _retry_with_pool(
            pool,
            lambda proxies: self.layerswap.create_swap(
                source_token=token, amount=send_human,
                destination_address=wallet, proxies=proxies,
            ),
        )
        swap_id = swap["swap_id"]
        deposit_address = swap["deposit_address"]
        if not swap_id:
            raise LayerswapError(f"API не вернул swap_id (raw={str(swap.get('raw'))[:300]})")
        if not deposit_address:
            raise LayerswapError("API не вернул deposit_address")
        swap_db.update_task(task["id"],
                            status=swap_db.STATUS_SWAP_CREATED,
                            layerswap_swap_id=swap_id,
                            deposit_address=deposit_address)
        logger.info(f"[{wallet}] {token}→{target_token} swap {swap_id} → deposit {deposit_address}")

        # 8) Реальная комиссия в fee_token на фактический deposit_address.
        try:
            fee_info = self.signer.transfer_fee(
                to=deposit_address, token=token, fee_token=fee_token,
            )
            fee_raw = int(fee_info["feeRaw"])
        except LiteSignerError as e:
            raise RuntimeError(f"не удалось рассчитать Lite-fee: {e}")

        # 9) Drain под ноль: send_raw = real_balance - fee, capped at layerswap max.
        if fee_token == token:
            # Стейбл/ETH со своим fee_token — fee вычитается из суммы перевода.
            send_raw = real_bal_raw - fee_raw
            if send_raw <= 0:
                raise RuntimeError(
                    f"баланс {token}={real_bal_raw} не покрывает fee={fee_raw}")
        else:
            # ETH-fee для стейбла: ETH балансом просто проверяем достаточность.
            eth_bal = int((info.get("balances") or {}).get("ETH", "0") or "0")
            if eth_bal < fee_raw:
                raise RuntimeError(
                    f"ETH баланс {eth_bal} < fee {fee_raw}")
            # Стейбл переводим целиком (fee платится отдельно в ETH).
            send_raw = real_bal_raw
        # Layerswap max: повторно ограничиваем после drain-расчёта.
        if lim and lim["max_amount"] > 0:
            max_raw = int((lim["max_amount"] * scale).to_integral_value())
            if send_raw > max_raw:
                logger.info(f"[{wallet}] {token}: drain {send_raw} > max {max_raw} — режем")
                send_raw = max_raw
        # Проверим повторно min после вычета fee.
        if lim and lim["min_amount"] > 0:
            min_raw = int((lim["min_amount"] * scale).to_integral_value())
            if send_raw < min_raw:
                swap_db.update_task(
                    task["id"], status=swap_db.STATUS_SKIPPED,
                    error_message=(f"после fee баланс {Decimal(send_raw)/scale} {token} "
                                   f"ниже Layerswap min={lim['min_amount']}"),
                )
                logger.info(f"[{wallet}] {token}: после fee ниже min — пропуск")
                return

        send_human = Decimal(send_raw) / scale
        # Обновим планируемую сумму в БД (для аудита)
        swap_db.update_task(task["id"],
                            amount_raw_planned=str(send_raw),
                            amount_human_planned=str(send_human))

        logger.info(f"[{wallet}] Lite transfer: {send_human} {token} → {deposit_address} "
                    f"(fee={fee_raw} {fee_token})")

        # 10) Lite transfer
        tx = self.signer.transfer(
            private_key=priv, to=deposit_address, token=token,
            amount_raw=str(send_raw), fee_token=fee_token,
        )
        lite_hash = tx.get("txHash")
        swap_db.update_task(task["id"],
                            status=swap_db.STATUS_LITE_TX_SENT,
                            lite_tx_hash=lite_hash)
        logger.info(f"[{wallet}] Lite tx: {lite_hash}")
        # Лог остатка для аудита drain
        try:
            info_after = self.signer.account_info(priv)
            left_raw = int((info_after.get("balances") or {}).get(token, "0") or "0")
            if left_raw > 0:
                logger.info(f"[{wallet}] {token} остаток на Lite: "
                            f"{Decimal(left_raw)/scale} ({left_raw} wei)")
        except Exception:
            pass

        # 11) Ждём Layerswap COMPLETED + Era баланс
        self._await_arrival(task, pool, wallet, swap_id, target_token)

    def _await_arrival(self, task: Dict[str, Any], pool: ProxyPool, wallet: str,
                       swap_id: str, target_token: str) -> None:
        """Ожидание прибытия средств на Era по уже созданному swap_id.

        Вынесено отдельно, чтобы повторный запуск мог дождаться ранее
        отправленного Lite-перевода, а не создавать новый свап (см. проверку
        идемпотентности в `_run_layerswap_task`).
        """
        swap_db.update_task(task["id"], status=swap_db.STATUS_AWAITING_ARRIVAL)
        deadline = time.monotonic() + ARRIVAL_TIMEOUT_SEC
        last_status = None
        net_errors_in_row = 0
        era_after = None
        while time.monotonic() < deadline:
            try:
                cur = self.layerswap.get_swap(swap_id, proxies=pool.current)
                net_errors_in_row = 0
            except LayerswapError as e:
                logger.warning(f"poll error (api): {e}")
                cur = None
            except Exception as e:
                cur = None
                if _is_net_error(e):
                    net_errors_in_row += 1
                    logger.warning(f"poll error (net) #{net_errors_in_row} "
                                   f"[{pool.kind}]: {e}")
                    # сразу пробуем переключиться на резерв
                    if pool.switch_to_reserve(str(e)):
                        # Немедленно дополнительная попытка с резервом
                        try:
                            cur = self.layerswap.get_swap(swap_id, proxies=pool.current)
                            net_errors_in_row = 0
                            logger.info(f"[{wallet}] резервная прокси сработала ✓")
                        except Exception as e2:
                            logger.warning(f"reserve proxy also failed: {e2}")
                else:
                    logger.warning(f"poll error (other): {e}")
            status = ((cur or {}).get("status") or "").lower()
            if status != last_status and status:
                logger.info(f"[{wallet}] Layerswap status: {status}")
                last_status = status
            if status in ("failed", "cancelled", "expired"):
                fr = (cur or {}).get("fail_reason") or ""
                raise LayerswapError(f"Layerswap terminal status: {status} ({fr})")
            if status == "completed":
                try:
                    era_after = self.era.get_balance_raw(wallet, target_token)
                except Exception:
                    era_after = None
                swap_db.update_task(
                    task["id"],
                    status=swap_db.STATUS_ARRIVED,
                    era_balance_after=str(era_after) if era_after is not None else None,
                    era_tx_hash=(cur or {}).get("destination_tx"),
                )
                logger.info(f"[{wallet}] {target_token} прибыло на Era ✓ "
                            f"(era_tx={(cur or {}).get('destination_tx')})")
                return
            time.sleep(LAYERSWAP_POLL_INTERVAL)
        raise TimeoutError(f"20 мин ожидания Era истекло (last status={last_status})")

    def _fail_all_remaining(self, tasks: List[Dict[str, Any]], reason: str) -> None:
        for t in tasks:
            if t.get("status") == swap_db.STATUS_PENDING:
                swap_db.update_task(
                    t["id"], status=swap_db.STATUS_SKIPPED,
                    error_message=reason[:500],
                )


__all__ = ["SwapExecutor", "ARRIVAL_TIMEOUT_SEC"]
