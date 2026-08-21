"""Тесты файловых sink-ов ``modules.simple_logger.setup_file_logging``.

Меню-обёртки модулей зовут ``setup_file_logging`` при каждом запуске пункта
меню, а главное меню крутится в бесконечном цикле. Без дедупликации третий
запуск «Check Proxy» за сессию писал бы каждую строку в log/*.log трижды и
держал три открытых дескриптора до конца процесса.
"""

from __future__ import annotations

import pytest

from loguru import logger

import modules.simple_logger as sl


@pytest.fixture()
def clean_sinks():
    """Снимает добавленные тестом sink-и, чтобы не течь в остальную сессию."""
    before = dict(sl._file_sinks)
    yield
    for key, sink_id in list(sl._file_sinks.items()):
        if key in before:
            continue
        try:
            logger.remove(sink_id)
        except ValueError:
            pass
        sl._file_sinks.pop(key, None)


def test_repeated_setup_reuses_single_sink(tmp_path, clean_sinks):
    """Повторный вызов для того же файла не плодит новый sink."""
    log_file = tmp_path / "module.log"

    first = sl.setup_file_logging(str(log_file))
    second = sl.setup_file_logging(str(log_file))
    third = sl.setup_file_logging(str(log_file))

    assert first == second == third
    assert len(sl._file_sinks) == 1


def test_same_file_via_different_path_forms_is_one_sink(tmp_path, clean_sinks):
    """Относительный и абсолютный путь к одному файлу — один и тот же sink."""
    log_file = tmp_path / "sub" / "module.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    first = sl.setup_file_logging(str(log_file))
    second = sl.setup_file_logging(str(log_file.parent / ".." / "sub" / "module.log"))

    assert first == second
    assert len(sl._file_sinks) == 1


def test_different_files_get_different_sinks(tmp_path, clean_sinks):
    """Разным файлам — разные sink-и: дедупликация не схлопывает лишнего."""
    first = sl.setup_file_logging(str(tmp_path / "a.log"))
    second = sl.setup_file_logging(str(tmp_path / "b.log"))

    assert first != second
    assert len(sl._file_sinks) == 2


def test_message_is_written_once(tmp_path, clean_sinks):
    """После трёх вызовов setup_file_logging строка попадает в файл один раз."""
    log_file = tmp_path / "once.log"
    for _ in range(3):
        sl.setup_file_logging(str(log_file))

    marker = "маркер-дедупликации-sink"
    logger.info(marker)

    text = log_file.read_text(encoding="utf-8")
    assert text.count(marker) == 1
