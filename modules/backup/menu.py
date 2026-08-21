"""Меню резервного копирования: локальные копии, SFTP, live-синхронизация.

Это мастер с несколькими уровнями и динамическими пунктами (списки копий
на диске и на сервере), поэтому меню собрано на ``ui.menu``/``ui.choose``,
а не на ``ModuleMenu``: набор пунктов зависит от того, включён ли SFTP.

Восстановление перезаписывает рабочие файлы проекта, поэтому каждый такой
пункт проходит через ``_confirm_restore`` — одно явное подтверждение с
ответом «нет» по умолчанию.
"""

from __future__ import annotations

from pathlib import Path

from config.modules import cfg_backup
from modules.backup.backup_manager import BackupManager
from modules.simple_logger import logger
from modules.ui import ui
from modules.ui.menu_model import BACK_KEY, MenuItem, render_items

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "modules" / "cfg_backup.py"


# ── Мелкие помощники отображения ────────────────────────────────────────

def _state(flag: bool, on: str, off: str) -> str:
    """Цветной статус «включено/выключено» одним видом во всём меню."""
    glyph = ui.glyphs.check if flag else ui.glyphs.cross
    color = ui.theme.FG_OK if flag else ui.theme.FG_ERR
    return f"{color}{glyph} {on if flag else off}{ui.theme.RESET}"


def _status_lines(manager: BackupManager) -> list[str]:
    rows = {"SFTP-сервер": _state(manager.sftp_enabled, "включён", "выключен")}
    if manager.sftp_enabled:
        rows["Live-синхронизация"] = _state(
            cfg_backup.SFTP_LIVE_SYNC_ENABLE, "активна", "отключена")
    rows["Локальные копии"] = f"{len(manager.list_local_backups())} шт. в backups/"
    return ui.key_values(rows)


def _restore_warning() -> list[str]:
    directories = ", ".join(f"{name}/" for name in cfg_backup.DIRECTORIES_TO_BACKUP)
    return [
        f"Файлы из архива перезапишут текущие: {directories}",
        "Отменить это будет нельзя.",
    ]


def _confirm_restore(source: str, note: str = "") -> bool:
    """Единственная точка подтверждения необратимого восстановления."""
    lines = [f"Источник: {source}", *_restore_warning()]
    if note:
        lines.append(note)
    ui.print_lines(ui.panel(
        "Восстановление перезапишет текущие данные", lines,
        color=ui.theme.FG_WARN,
    ))
    if ui.confirm("Продолжить восстановление?", default=False):
        return True
    logger.info("Восстановление отменено — файлы не тронуты")
    return False


def _pick_backup(title: str, backups: list[str]) -> str | None:
    """Выбор копии из списка. ``None`` — пользователь отказался."""
    options = [(f"{index}. {name}", name)
               for index, name in enumerate(backups, 1)]
    chosen = ui.choose(title, options, back_label="Отмена")
    return None if chosen in (None, BACK_KEY) else chosen


# ── Действия меню ───────────────────────────────────────────────────────

def _handle_create(manager: BackupManager) -> None:
    upload = False
    if manager.sftp_enabled:
        upload = ui.confirm("Загрузить копию на SFTP-сервер?", default=True)
    manager.create_backup(upload_to_sftp=upload)


def _handle_list_local(manager: BackupManager) -> None:
    manager.show_local_backups_info()


def _handle_restore_local(manager: BackupManager) -> None:
    manager.show_local_backups_info()
    backups = manager.list_local_backups()
    if not backups:
        return
    selected = _pick_backup("Из какой копии восстанавливать?", backups)
    if selected is None:
        return
    if _confirm_restore(selected):
        manager.restore_local_backup(selected)


def _handle_cleanup_local(manager: BackupManager) -> None:
    if ui.confirm(
        f"Удалить локальные копии, кроме последних "
        f"{cfg_backup.MAX_BACKUPS_TO_KEEP}?", default=True,
    ):
        manager.cleanup_old_local_backups()


def _handle_list_sftp(manager: BackupManager) -> None:
    manager.show_sftp_backups_info()


def _handle_download_sftp(manager: BackupManager) -> None:
    manager.show_sftp_backups_info()
    backups = manager.list_sftp_backups()
    if not backups:
        return
    selected = _pick_backup("Какую копию скачать?", backups)
    if selected is not None:
        manager.download_from_sftp(selected)


def _handle_restore_sftp(manager: BackupManager) -> None:
    logger.info("📥 Скачиваем последнюю копию с SFTP…")
    if not manager.download_from_sftp():
        return
    if not _confirm_restore("последняя копия с SFTP-сервера"):
        return
    backups = manager.list_local_backups()
    if backups:
        manager.restore_local_backup(backups[0])


def _handle_cleanup_sftp(manager: BackupManager) -> None:
    if ui.confirm(
        f"Удалить копии на SFTP, кроме последних "
        f"{cfg_backup.MAX_BACKUPS_TO_KEEP}?", default=True,
    ):
        manager.cleanup_old_sftp_backups()


def _handle_test_sftp(manager: BackupManager) -> None:
    manager.test_sftp_connection()


def _handle_live_create(manager: BackupManager) -> None:
    logger.info("🔴 Обновляем live-копию…")
    manager.create_live_backup()


def _handle_live_restore(manager: BackupManager) -> None:
    if _confirm_restore(
        f"live-копия {manager.get_live_backup_name()}",
        "Архив будет скачан с сервера и расшифрован.",
    ):
        manager.restore_live_backup()


def _handle_live_delete(manager: BackupManager) -> None:
    manager.delete_live_backup_with_confirmation()


def show_live_backup_info(manager: BackupManager) -> None:
    """Состояние live-копии: имя файла, шифрование, наличие на сервере."""
    if not manager.sftp_enabled:
        logger.error("SFTP-бэкап выключен — live-копии нет")
        return
    if not cfg_backup.SFTP_LIVE_SYNC_ENABLE:
        logger.warning(
            "Live-синхронизация отключена — включите её пунктом "
            "«Live-синхронизация»")
        return

    sftp_config = cfg_backup.SFTP_SERVER_INTO_BACKUP
    exists = manager.check_live_backup_exists()
    from_config = bool(sftp_config.get("password_encryption"))

    hints = [
        "Копия обновляется каждые 60 секунд, пока программа запущена.",
        "На сервере лежит только одна актуальная версия.",
        "Развернуть её можно на любом устройстве с тем же паролем.",
    ]
    if not exists:
        hints.insert(0, "Создайте её пунктом «Обновить live-копию».")

    ui.print_lines(ui.panel("Live-копия", [
        *ui.key_values({
            "Файл": manager.get_live_backup_name(),
            "Идентификатор": sftp_config.get("identificator") or "не задан",
            "На сервере": _state(exists, "есть", "не найдена"),
            "Шифрование": ("пароль из конфигурации" if from_config
                           else "пароль спросим при обращении"),
        }),
        "",
        *ui.bullet_list(hints),
    ]))


# ── Переключатели настроек ──────────────────────────────────────────────

def _write_config_flag(name: str, current: bool, new: bool) -> bool:
    """Переписывает булев флаг в cfg_backup.py и обновляет его в памяти.

    Настройка обязана пережить перезапуск, поэтому правится сам файл
    конфигурации, а не только загруженный модуль.
    """
    old_line = f"{name} = {current}"
    try:
        content = CONFIG_PATH.read_text(encoding="utf-8")
        if old_line not in content:
            logger.error(f"Не нашли строку «{old_line}» в {CONFIG_PATH.name}")
            return False
        CONFIG_PATH.write_text(
            content.replace(old_line, f"{name} = {new}"), encoding="utf-8")
    except Exception as exc:
        logger.error(f"Не удалось обновить {CONFIG_PATH.name}: {exc}")
        return False
    setattr(cfg_backup, name, new)
    return True


def toggle_live_sync() -> None:
    """Включает или выключает live-синхронизацию с SFTP-сервером."""
    enabled = cfg_backup.SFTP_LIVE_SYNC_ENABLE

    ui.print_lines(ui.panel("Live-синхронизация", [
        *ui.key_values({"Сейчас": _state(enabled, "включена", "выключена")}),
        "",
        *ui.bullet_list([
            "Программа сама следит за изменениями файлов проекта.",
            "Изменения уезжают на SFTP зашифрованным архивом.",
            "На сервере хранится одна актуальная копия.",
        ]),
    ]))

    if not cfg_backup.SFTP_SERVER_INTO_BACKUP_ENABLE:
        logger.error(
            "Live-синхронизация работает поверх SFTP — сначала включите "
            "SFTP-бэкап")
        return

    choice = ui.choose("Что делаем?", [
        ("✅ Включить live-синхронизацию", "enable"),
        ("⛔ Выключить live-синхронизацию", "disable"),
    ], back_label="Ничего не менять")
    if choice in (None, BACK_KEY):
        return

    new_state = choice == "enable"
    word = "включена" if new_state else "выключена"
    if new_state == enabled:
        logger.info(f"Live-синхронизация и так {word}")
        return
    if not _write_config_flag("SFTP_LIVE_SYNC_ENABLE", enabled, new_state):
        return

    logger.success(f"Live-синхронизация {word}")
    if new_state:
        ui.print_lines(*ui.bullet_list([
            "Мониторинг запустится сам при следующем старте программы.",
            "Изменения проверяются каждые 60 секунд.",
        ]))


def _sftp_ready_to_enable() -> bool:
    """Проверяет настройки и связь перед включением выгрузки."""
    sftp_config = cfg_backup.SFTP_SERVER_INTO_BACKUP
    if not sftp_config.get("host") or not sftp_config.get("username"):
        ui.print_lines(ui.panel("SFTP-сервер не настроен", [
            f"Заполните в config/modules/{CONFIG_PATH.name}:",
            *ui.bullet_list([
                "host — адрес сервера",
                "username — имя пользователя",
                "password или key_file — способ авторизации",
            ]),
        ], color=ui.theme.FG_ERR))
        return False

    logger.info("🧪 Проверяем подключение к SFTP-серверу…")
    if BackupManager().test_sftp_connection():
        return True

    logger.error(
        f"Подключиться не удалось — проверьте настройки в "
        f"config/modules/{CONFIG_PATH.name}")
    return ui.confirm("Всё равно включить выгрузку на SFTP?", default=False)


def toggle_sftp_backup() -> None:
    """Включает или выключает выгрузку копий на SFTP-сервер."""
    enabled = cfg_backup.SFTP_SERVER_INTO_BACKUP_ENABLE
    sftp_config = cfg_backup.SFTP_SERVER_INTO_BACKUP

    ui.print_lines(ui.panel("SFTP-бэкап", ui.key_values({
        "Сейчас": _state(enabled, "включён", "выключен"),
        "Сервер": sftp_config.get("host") or "не указан",
        "Пользователь": sftp_config.get("username") or "не указан",
    })))

    choice = ui.choose("Что делаем?", [
        ("✅ Включить выгрузку на SFTP", "enable"),
        ("⛔ Выключить выгрузку на SFTP", "disable"),
    ], back_label="Ничего не менять")
    if choice in (None, BACK_KEY):
        return

    new_state = choice == "enable"
    word = "включён" if new_state else "выключен"
    if new_state == enabled:
        logger.info(f"SFTP-бэкап и так {word}")
        return
    if new_state and not _sftp_ready_to_enable():
        return
    if not _write_config_flag(
        "SFTP_SERVER_INTO_BACKUP_ENABLE", enabled, new_state
    ):
        return

    logger.success(f"SFTP-бэкап {word}")
    if new_state:
        logger.info("Новые копии будут автоматически уезжать на сервер")


# ── Сборка меню ─────────────────────────────────────────────────────────

_HANDLERS = {
    "create": _handle_create,
    "list_local": _handle_list_local,
    "restore_local": _handle_restore_local,
    "cleanup_local": _handle_cleanup_local,
    "list_sftp": _handle_list_sftp,
    "download_sftp": _handle_download_sftp,
    "restore_sftp": _handle_restore_sftp,
    "cleanup_sftp": _handle_cleanup_sftp,
    "test_sftp": _handle_test_sftp,
    "live_create": _handle_live_create,
    "live_restore": _handle_live_restore,
    "live_info": show_live_backup_info,
    "live_delete": _handle_live_delete,
}

# Переключатели настроек: после них менеджер пересоздаётся.
_TOGGLES = {
    "live_toggle": toggle_live_sync,
    "toggle_sftp": toggle_sftp_backup,
}


def _items(manager: BackupManager) -> list[MenuItem]:
    """Пункты меню: часть появляется только при включённом SFTP."""
    keep = cfg_backup.MAX_BACKUPS_TO_KEEP
    items = [
        MenuItem("create", "Создать копию",
                 "заархивировать данные проекта", icon="📦"),
        MenuItem("list_local", "Локальные копии",
                 "показать, что лежит в backups/", icon="📋"),
        MenuItem("restore_local", "Восстановить из локальной копии",
                 "перезапишет текущие файлы", icon="♻️"),
        MenuItem("cleanup_local", "Убрать старые локальные копии",
                 f"оставить последние {keep}", icon="🧹"),
    ]

    if manager.sftp_enabled:
        live_on = cfg_backup.SFTP_LIVE_SYNC_ENABLE
        items += [
            MenuItem("list_sftp", "Копии на SFTP",
                     "показать, что лежит на сервере", icon="☁️"),
            MenuItem("download_sftp", "Скачать копию с SFTP",
                     "положить архив в backups/", icon="⬇️"),
            MenuItem("restore_sftp", "Восстановить с SFTP",
                     "скачать последнюю и распаковать", icon="♻️"),
            MenuItem("cleanup_sftp", "Убрать старые копии на SFTP",
                     f"оставить последние {keep}", icon="🧹"),
            MenuItem("test_sftp", "Проверить связь с SFTP",
                     "тестовое подключение к серверу", icon="🧪"),
            MenuItem("live_toggle", "Live-синхронизация",
                     f"сейчас {'включена' if live_on else 'выключена'}",
                     icon="🔄"),
        ]
        if live_on:
            items += [
                MenuItem("live_create", "Обновить live-копию",
                         "снять и зашифровать прямо сейчас", icon="🔴"),
                MenuItem("live_restore", "Восстановить из live-копии",
                         "перезапишет текущие файлы", icon="📥"),
                MenuItem("live_info", "Состояние live-копии",
                         "файл, шифрование, наличие на сервере", icon="ℹ️"),
                MenuItem("live_delete", "Удалить live-копию с сервера",
                         "локальные копии останутся", icon="🗑️"),
            ]
        items.append(MenuItem("toggle_sftp", "Выключить SFTP-бэкап",
                              "перестать выгружать копии на сервер",
                              icon="⚙️"))
    else:
        items.append(MenuItem("toggle_sftp", "Настроить SFTP-бэкап",
                              "проверить связь и включить выгрузку",
                              icon="⚙️"))

    items.append(MenuItem(BACK_KEY, "Назад", "", icon="←"))
    return items


def backup_menu() -> None:
    """Меню резервного копирования — точка входа из главного меню."""
    manager = BackupManager()

    while True:
        ui.print_lines(ui.panel("Резервное копирование", _status_lines(manager)))

        choice = ui.menu("Что делаем с копиями?", render_items(_items(manager)))
        if choice in (None, BACK_KEY):
            return

        handler = _HANDLERS.get(choice)
        if handler is not None:
            handler(manager)
        elif choice in _TOGGLES:
            _TOGGLES[choice]()
            # Настройки изменились — менеджер читает их при создании.
            manager = BackupManager()

        ui.pause()


__all__ = [
    "backup_menu", "toggle_live_sync", "toggle_sftp_backup",
    "show_live_backup_info",
]
