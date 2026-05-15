"""
Централизованный менеджер данных.
Все данные хранятся в одном CSV файле data/data_<profile>.csv

Заголовки:
  name, private_key, proxy, reserve_proxy, wallet_address, mnemonic,
  sol_address, sol_private_key, discord_token, email, email_password,
  email_imap, referral_code, evm_cex_address, sol_cex_address,
  transfer_amount

Назначение полей CEX/transfer:
  evm_cex_address  — адрес-получатель для EVM-переводов (например, депозит CEX)
                     используется как to_wallet в Transfer Wallets / Transfer ERC20.
  sol_cex_address  — адрес-получатель для SOL-переводов (депозит CEX).
  transfer_amount  — сумма для модулей Transfer Wallets / Transfer ERC20.
                     Формат:
                       0.1-0.2     → диапазон суммы в нативном токене / токенах
                       "0.1-0.2"   → проценты от баланса (в кавычках)
                       0.1-0.2%    → проценты от баланса (с символом %)
                       10-20token  → токены (для ERC20 модуля)

Файлы данных ОБЯЗАНЫ начинаться с 'data_' и заканчиваться на '.csv'.
Если в data/ несколько таких файлов — пользователю предлагается выбор.

При первом обращении к менеджеру выполняется миграция всех *.csv в data/:
к файлам со «своей» схемой (заголовки — подмножество HEADERS) дописываются
недостающие колонки, существующие данные не повреждаются.
"""

import csv
import random
from pathlib import Path
from typing import List, Optional, Dict
from modules.simple_logger import logger

try:
    from config.modules.general_config import SHUFLE_ACCOUNTS as _SHUFLE_ACCOUNTS
except ImportError:
    _SHUFLE_ACCOUNTS = False

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data'

HEADERS = [
    'name', 'private_key', 'proxy', 'reserve_proxy',
    'wallet_address', 'mnemonic', 'sol_address', 'sol_private_key',
    'discord_token', 'email', 'email_password', 'email_imap',
    'referral_code', 'evm_cex_address', 'sol_cex_address',
    'transfer_amount',
]
DEFAULT_DATA_FILE = DATA_DIR / 'data.csv'

# Глобальное хранилище загруженных данных
_loaded_rows: List[Dict[str, str]] = []
_loaded_file: Optional[str] = None
_selected_data_file: Optional[Path] = None
_migrated_once: bool = False


def _migrate_csv_file(filepath: Path) -> bool:
    """Дописывает недостающие колонки HEADERS к файлу, если его схема — подмножество HEADERS.

    Возвращает True, если файл был изменён.
    Файлы с колонками, отсутствующими в HEADERS, пропускаются — у них чужая схема.
    Существующие строки данных переносятся как есть; новые колонки получают пустые значения.
    """
    try:
        with open(filepath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return False
            rows = list(reader)
    except Exception as e:
        logger.warning(f"Не удалось прочитать {filepath.name} для миграции: {e}")
        return False

    header_clean = [h.strip() for h in header]
    header_set = set(header_clean)

    foreign = header_set - set(HEADERS)
    if foreign:
        return False

    missing = [h for h in HEADERS if h not in header_set]
    if not missing:
        return False

    new_header = list(header) + missing

    tmp = filepath.with_suffix(filepath.suffix + '.tmp')
    try:
        with open(tmp, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(new_header)
            for row in rows:
                writer.writerow(row)
        tmp.replace(filepath)
        logger.info(f"Файл {filepath.name}: добавлены колонки {missing}")
        return True
    except Exception as e:
        logger.error(f"Не удалось обновить {filepath.name}: {e}")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def migrate_all_data_files() -> int:
    """Сканирует data/ на *.csv и дописывает недостающие колонки. Возвращает число изменённых файлов."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    updated = 0
    for f in sorted(DATA_DIR.glob('*.csv')):
        if _migrate_csv_file(f):
            updated += 1
    return updated


def _run_migration_once() -> None:
    """Запускает миграцию один раз за процесс."""
    global _migrated_once
    if _migrated_once:
        return
    _migrated_once = True
    try:
        migrate_all_data_files()
    except Exception as e:
        logger.warning(f"Ошибка миграции CSV: {e}")


def _ensure_data_file(filepath: Path = None) -> Path:
    """Создаёт файл data.csv с заголовками, если не существует, и мигрирует существующие."""
    filepath = filepath or DEFAULT_DATA_FILE
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _run_migration_once()

    if not filepath.exists():
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writeheader()
        logger.info(f"Создан файл {filepath.name} с заголовками: {','.join(HEADERS)}")

    return filepath


def list_data_files() -> List[Path]:
    """Возвращает список data_*.csv файлов в data/."""
    files = []
    for p in sorted(DATA_DIR.glob('data_*.csv')):
        files.append(p)
    # Также включаем data.csv (без суффикса) для обратной совместимости
    default = DATA_DIR / 'data.csv'
    if default.exists() and default not in files:
        files.insert(0, default)
    return files


def select_data_file() -> Path:
    """Интерактивный выбор CSV файла для работы.
    Вызывается один раз при старте приложения.
    Результат сохраняется глобально и используется load_data() по умолчанию.
    """
    global _selected_data_file

    _ensure_data_file()
    files = list_data_files()

    if len(files) == 0:
        _selected_data_file = _ensure_data_file()
        return _selected_data_file

    if len(files) == 1:
        logger.info(f"Используется файл данных: {files[0].name}")
        _selected_data_file = files[0]
        return _selected_data_file

    # Несколько файлов — спрашиваем
    try:
        from questionary import Choice, select
        choices = [Choice(f'   📄 {f.name}', str(f)) for f in files]
        selected = select(
            "\n╔════════════════════════════════════════════════╗\n"
            "║      Выбор файла данных / Select data file     ║\n"
            "╚════════════════════════════════════════════════╝",
            choices=choices,
            qmark='📂',
            pointer='👉'
        ).ask()

        if selected:
            logger.success(f"Выбран файл данных: {Path(selected).name}")
            _selected_data_file = Path(selected)
            return _selected_data_file
    except Exception:
        pass

    # Fallback — data.csv
    _selected_data_file = _ensure_data_file()
    return _selected_data_file


def load_data(filepath: Path = None, force_reload: bool = False,
              shuffle: Optional[bool] = None) -> List[Dict[str, str]]:
    """Загружает данные из CSV файла. Кэширует результат.

    Если SHUFLE_ACCOUNTS=True в general_config (или явно передано shuffle=True),
    возвращает свежеперемешанную КОПИЮ списка при каждом вызове — кешированные
    "первичные" строки в исходном порядке всегда сохраняются нетронутыми.
    """
    global _loaded_rows, _loaded_file

    if filepath is None:
        filepath = _selected_data_file or DEFAULT_DATA_FILE

    filepath_str = str(filepath)

    rows: List[Dict[str, str]]
    if _loaded_rows and _loaded_file == filepath_str and not force_reload:
        rows = _loaded_rows
    else:
        _ensure_data_file(filepath)
        rows = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Нормализуем: пустые значения → пустая строка
                    normalized = {h: (row.get(h, '') or '').strip() for h in HEADERS}
                    rows.append(normalized)
        except Exception as e:
            logger.error(f"Ошибка чтения {filepath}: {e}")
            return []

        _loaded_rows = rows
        _loaded_file = filepath_str
        logger.info(f"Загружено {len(rows)} записей из {filepath.name}")

    do_shuffle = _SHUFLE_ACCOUNTS if shuffle is None else bool(shuffle)
    if do_shuffle and len(rows) > 1:
        shuffled = list(rows)
        random.shuffle(shuffled)
        return shuffled
    return rows


def reload_data(filepath: Path = None) -> List[Dict[str, str]]:
    """Принудительная перезагрузка данных."""
    return load_data(filepath, force_reload=True)


# ──────────────────────────────────────────────
# Хелперы для получения отдельных полей
# ──────────────────────────────────────────────

def get_private_keys(filepath: Path = None) -> List[str]:
    """Возвращает список приватных ключей (непустых)."""
    rows = load_data(filepath)
    return [r['private_key'] for r in rows if r['private_key']]


def get_proxies(filepath: Path = None) -> List[str]:
    """Возвращает список прокси (непустых)."""
    rows = load_data(filepath)
    return [r['proxy'] for r in rows if r['proxy']]


def get_reserve_proxies(filepath: Path = None) -> List[str]:
    """Возвращает список резервных прокси (непустых)."""
    rows = load_data(filepath)
    return [r['reserve_proxy'] for r in rows if r['reserve_proxy']]


def get_wallet_addresses(filepath: Path = None) -> List[str]:
    """Возвращает список адресов кошельков (непустых)."""
    rows = load_data(filepath)
    return [r['wallet_address'] for r in rows if r['wallet_address']]


def get_mnemonics(filepath: Path = None) -> List[str]:
    """Возвращает список мнемоник (непустых)."""
    rows = load_data(filepath)
    return [r['mnemonic'] for r in rows if r['mnemonic']]


def get_sol_addresses(filepath: Path = None) -> List[str]:
    """Возвращает список SOL-адресов (непустых)."""
    rows = load_data(filepath)
    return [r['sol_address'] for r in rows if r['sol_address']]


def get_discord_tokens(filepath: Path = None) -> List[str]:
    """Возвращает список Discord-токенов (непустых)."""
    rows = load_data(filepath)
    return [r['discord_token'] for r in rows if r['discord_token']]


def get_emails(filepath: Path = None) -> List[Dict[str, str]]:
    """Возвращает список email-записей (email, email_password, email_imap)."""
    rows = load_data(filepath)
    result = []
    for r in rows:
        if r['email']:
            result.append({
                'email': r['email'],
                'password': r['email_password'],
                'imap_domain': r['email_imap'],
            })
    return result


def get_evm_cex_addresses(filepath: Path = None) -> List[str]:
    """Возвращает список EVM-адресов CEX для вывода (непустых)."""
    rows = load_data(filepath)
    return [r['evm_cex_address'] for r in rows if r['evm_cex_address']]


def get_sol_cex_addresses(filepath: Path = None) -> List[str]:
    """Возвращает список SOL-адресов CEX для вывода (непустых)."""
    rows = load_data(filepath)
    return [r['sol_cex_address'] for r in rows if r['sol_cex_address']]


def get_referral_code_for_key(private_key: str, filepath: Path = None) -> Optional[str]:
    """Возвращает реферальный код, привязанный к приватному ключу."""
    rows = load_data(filepath)
    for r in rows:
        if r['private_key'] == private_key.strip():
            return r['referral_code'] if r.get('referral_code') else None
    return None


def get_proxy_for_key(private_key: str, filepath: Path = None) -> Optional[str]:
    """Возвращает прокси, привязанный к приватному ключу."""
    rows = load_data(filepath)
    for r in rows:
        if r['private_key'] == private_key.strip():
            return r['proxy'] if r['proxy'] else None
    return None


def get_reserve_proxy_for_key(private_key: str, filepath: Path = None) -> Optional[str]:
    """Возвращает резервный прокси для приватного ключа."""
    rows = load_data(filepath)
    for r in rows:
        if r['private_key'] == private_key.strip():
            return r['reserve_proxy'] if r['reserve_proxy'] else None
    return None


def get_evm_cex_address_for_key(private_key: str, filepath: Path = None) -> Optional[str]:
    """Возвращает EVM CEX-адрес, привязанный к приватному ключу."""
    rows = load_data(filepath)
    for r in rows:
        if r['private_key'] == private_key.strip():
            return r['evm_cex_address'] if r['evm_cex_address'] else None
    return None


def get_sol_cex_address_for_key(private_key: str, filepath: Path = None) -> Optional[str]:
    """Возвращает SOL CEX-адрес, привязанный к приватному ключу.

    Принимает EVM private_key — ключевое поле строки. Для поиска по sol_private_key
    используйте get_sol_cex_address_for_sol_key.
    """
    rows = load_data(filepath)
    for r in rows:
        if r['private_key'] == private_key.strip():
            return r['sol_cex_address'] if r['sol_cex_address'] else None
    return None


def get_sol_cex_address_for_sol_key(sol_private_key: str, filepath: Path = None) -> Optional[str]:
    """Возвращает SOL CEX-адрес по sol_private_key."""
    rows = load_data(filepath)
    for r in rows:
        if r['sol_private_key'] == sol_private_key.strip():
            return r['sol_cex_address'] if r['sol_cex_address'] else None
    return None


def get_transfer_amount_for_key(private_key: str, filepath: Path = None) -> Optional[str]:
    """Возвращает значение transfer_amount по приватному ключу."""
    rows = load_data(filepath)
    for r in rows:
        if r['private_key'] == private_key.strip():
            return r['transfer_amount'] if r['transfer_amount'] else None
    return None


def get_transfer_rows(filepath: Path = None) -> List[Dict[str, str]]:
    """Возвращает строки для модулей переводов (Transfer W2W / Transfer ERC20).

    Каждая строка — словарь, совместимый со старым форматом transfer_token.csv:
        from_wallet  → private_key
        to_wallet    → evm_cex_address
        amount       → transfer_amount

    Возвращаются только строки, где заполнены все три ключевых поля.
    """
    rows = load_data(filepath)
    out: List[Dict[str, str]] = []
    for r in rows:
        from_w = r.get('private_key', '').strip()
        to_w = r.get('evm_cex_address', '').strip()
        amt = r.get('transfer_amount', '').strip()
        if from_w and to_w and amt:
            out.append({
                'from_wallet': from_w,
                'to_wallet': to_w,
                'amount': amt,
            })
    return out


def get_row_by_index(index: int, filepath: Path = None) -> Optional[Dict[str, str]]:
    """Возвращает строку по индексу."""
    rows = load_data(filepath)
    if 0 <= index < len(rows):
        return rows[index]
    return None


def get_proxy_with_fallback(index: int, filepath: Path = None) -> Optional[str]:
    """Возвращает прокси по индексу, если пуст — резервный."""
    row = get_row_by_index(index, filepath)
    if row is None:
        return None
    return row['proxy'] or row['reserve_proxy'] or None


__all__ = [
    'HEADERS', 'DEFAULT_DATA_FILE', 'DATA_DIR',
    'select_data_file', 'load_data', 'reload_data',
    'list_data_files', 'migrate_all_data_files',
    'get_private_keys', 'get_proxies', 'get_reserve_proxies',
    'get_wallet_addresses', 'get_mnemonics', 'get_sol_addresses',
    'get_discord_tokens', 'get_emails',
    'get_evm_cex_addresses', 'get_sol_cex_addresses',
    'get_referral_code_for_key',
    'get_proxy_for_key', 'get_reserve_proxy_for_key',
    'get_evm_cex_address_for_key', 'get_sol_cex_address_for_key',
    'get_sol_cex_address_for_sol_key',
    'get_transfer_amount_for_key', 'get_transfer_rows',
    'get_row_by_index', 'get_proxy_with_fallback',
]
