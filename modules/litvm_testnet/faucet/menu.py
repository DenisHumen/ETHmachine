"""LiteForge faucet — меню пресета."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from colorama import Fore, Style
from eth_account import Account
from questionary import Choice, select

from config.modules.general_config import NUM_THREADS
from config.modules.cfg_litvm_testnet import (
    LITVM_FAUCET_CAPTCHA_SITEKEY,
    LITVM_FAUCET_CAPTCHA_TYPE,
)
from modules.captcha.manager import (
    SERVICE_CONFIG_FIELDS,
    configured_services_for_type,
    services_for_captcha_type,
)
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.faucet import database as db
from modules.litvm_testnet.faucet.faucet_client import is_test_sitekey
from modules.litvm_testnet.faucet.worker import process_wallet
from modules.litvm_testnet.vercel_bypass import get_client


def _check_sitekey_configured() -> bool:
    key = (LITVM_FAUCET_CAPTCHA_SITEKEY or "").strip()
    if not key:
        log_simple(
            "❌ LITVM_FAUCET_CAPTCHA_SITEKEY пустой в config/modules/cfg_litvm_testnet.py.",
            "error",
        )
        log_simple(
            "   Найди data-sitekey у Turnstile/hCaptcha-виджета в DevTools на "
            "liteforge.hub.caldera.xyz и положи в LITVM_FAUCET_CAPTCHA_SITEKEY.",
            "info",
        )
        return False
    if is_test_sitekey(key):
        log_simple(
            f"❌ LITVM_FAUCET_CAPTCHA_SITEKEY='{key}' — это публичный test-ключ.",
            "error",
        )
        log_simple(
            "   CapSolver/2captcha/etc отказываются его решать "
            "('We don't support this service'). Нужен реальный sitekey со страницы.",
            "info",
        )
        return False
    return True


def _check_captcha_ready(captcha_type: str) -> bool:
    if configured_services_for_type(captcha_type):
        return True
    supported = services_for_captcha_type(captcha_type)
    log_simple(
        f"❌ Нет API-ключа ни для одного сервиса, поддерживающего '{captcha_type}'.",
        "error",
    )
    if supported:
        log_simple(
            f"   Поддерживают '{captcha_type}': {', '.join(supported)}",
            "info",
        )
        fields = ", ".join(f"{s} → {SERVICE_CONFIG_FIELDS[s]}" for s in supported)
        log_simple(
            f"   Заполните любой ключ в config/modules/general_config.py: {fields}",
            "info",
        )
    return False


def _build_menu() -> str | None:
    return select(
        "🚰 LiteForge Faucet (testnet zkLTC):",
        choices=[
            Choice("▶️  Продолжить", "continue"),
            Choice("🗑️  Очистить статусы и начать заново", "reset"),
            Choice("📊 Статистика БД", "stats"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🚰",
        pointer="👉",
    ).ask()


def _show_stats() -> None:
    stats = db.get_statistics()
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}LiteForge Faucet — статистика{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    if not stats or stats.get("total", 0) == 0:
        print(f"  {Fore.YELLOW}БД пуста{Style.RESET_ALL}")
    else:
        for key, val in stats.items():
            if key == "total":
                continue
            print(f"  {key:<22} {val}")
        print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
        print(f"  {'total':<22} {stats.get('total', 0)}")

    avg = db.avg_arrival_seconds()
    if avg is not None:
        print(f"  {'avg arrival':<22} {avg:.0f}s")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _format_summary(stats: dict) -> str:
    parts = []
    for key in ("arrived", "requested", "cooldown", "ineligible", "failed",
                "in_progress", "pending"):
        val = int(stats.get(key, 0) or 0)
        if val:
            parts.append(f"{key}={val}")
    parts.append(f"total={int(stats.get('total', 0) or 0)}")
    return " · ".join(parts)


def _derive_address(record: dict) -> str | None:
    pk = (record.get("private_key") or "").strip()
    if not pk:
        return None
    if not pk.startswith("0x"):
        pk = "0x" + pk
    try:
        return Account.from_key(pk).address
    except Exception:
        return None


def _partition_by_history(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Делит кошельки на (новые, уже запрашивавшие).

    «Новый» = в `request_history` нет ни одной записи по этому адресу.
    Новые идут первой фазой — приоритет раздать кран адресам, которые ещё
    ни разу его не видели (особенно важно при ограниченных captcha/proxy
    ресурсах). Если все кошельки уже хотя бы раз запрашивали — поведение
    совпадает с прежним (один проход в порядке data.csv).

    Записи с битым private_key падают в «новые»: process_wallet их сам
    отбросит, но они хотя бы окажутся в начале лога."""
    addresses = [_derive_address(r) for r in records]
    valid = [a for a in addresses if a]
    ever_requested = db.wallets_with_request_history(valid) if valid else set()
    new_wallets: list[dict] = []
    old_wallets: list[dict] = []
    for rec, addr in zip(records, addresses):
        if addr and addr.lower() in ever_requested:
            old_wallets.append(rec)
        else:
            new_wallets.append(rec)
    return new_wallets, old_wallets


def _run_phase(records: list[dict], start_offset: int, total: int,
               threads: int) -> bool:
    """Прогоняет батч кошельков (последовательно или через ThreadPoolExecutor).

    `start_offset` — сколько кошельков уже обработано в предыдущих фазах,
    чтобы лог-индекс `idx/total` оставался сквозным 1..total.
    Возвращает True, если пользователь нажал Ctrl+C."""
    if not records:
        return False
    if threads <= 1 or len(records) <= 1:
        for i, rec in enumerate(records, 1):
            try:
                process_wallet(rec, start_offset + i, total)
            except KeyboardInterrupt:
                log_simple("⚠ прервано пользователем (состояние сохранено в БД)", "warning")
                return True
        return False
    with ThreadPoolExecutor(max_workers=threads, thread_name_prefix="litvm-faucet") as ex:
        futs = [ex.submit(process_wallet, rec, start_offset + i, total)
                for i, rec in enumerate(records, 1)]
        try:
            for fut in as_completed(futs):
                fut.result()
        except KeyboardInterrupt:
            for f in futs:
                f.cancel()
            log_simple("⚠ прервано пользователем (состояние сохранено в БД)", "warning")
            return True
    return False


def _run_continue() -> None:
    if not _check_captcha_ready(LITVM_FAUCET_CAPTCHA_TYPE):
        return
    if not _check_sitekey_configured():
        return

    rows = load_data()
    if not rows:
        log_simple("Нет данных в data/data.csv", "error")
        return

    records = [r for r in rows if (r.get("private_key") or "").strip()]
    total = len(records)
    if total == 0:
        log_simple("Нет кошельков с private_key", "error")
        return

    set_auto_progress(False)
    threads = max(1, min(int(NUM_THREADS), total))

    new_wallets, old_wallets = _partition_by_history(records)
    if new_wallets and old_wallets:
        log_simple(
            f"🚰 LiteForge Faucet: старт для {total} кошельков (threads={threads}); "
            f"приоритет — {len(new_wallets)} новых (нет в request_history), "
            f"далее {len(old_wallets)} ранее запрошенных",
            "info",
        )
    else:
        log_simple(
            f"🚰 LiteForge Faucet: старт для {total} кошельков (threads={threads})",
            "info",
        )

    interrupted = False
    running_offset = 0
    for phase_records in (new_wallets, old_wallets):
        if not phase_records:
            continue
        interrupted = _run_phase(phase_records, running_offset, total, threads)
        if interrupted:
            break
        running_offset += len(phase_records)

    # Закрываем patchright — иначе фоновый Chromium висит до выхода из ETHmachine.
    try:
        get_client().close()
    except Exception:
        pass

    stats = db.get_statistics()
    summary = _format_summary(stats)
    if interrupted:
        log_simple(f"🏁 остановлено · {summary}", "warning")
    else:
        log_simple(f"🏁 готово · {summary}", "success")


def run_litvm_faucet() -> None:
    db.init_database()

    while True:
        action = _build_menu()
        if action is None or action == "back":
            return
        if action == "continue":
            try:
                _run_continue()
            except KeyboardInterrupt:
                pass
        elif action == "reset":
            confirm = select(
                "Очистить статусы задач? (история запросов и кулдауны сохранятся)",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_tasks()
                log_simple("🗑️ статусы очищены, история кулдаунов сохранена", "success")
        elif action == "stats":
            _show_stats()
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
