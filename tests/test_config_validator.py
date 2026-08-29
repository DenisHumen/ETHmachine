"""Тесты предстартового валидатора ``modules.config_validator``.

Проверка значений из ``config/modules/*.py`` долго была мёртвым кодом: метод
существовал, но его никто не вызывал. Здесь закреплено, что он снова в цепочке
и что все его находки — предупреждения, а не критические ошибки: main.py
отказывается стартовать при errors, и обновление по ``git pull`` не должно
внезапно запирать пользователя с давно лежащим у него конфигом.
"""

from __future__ import annotations

from modules.config_validator import ConfigValidator


def test_config_modules_check_is_wired_into_check_config_files(monkeypatch):
    """check_config_files обязан звать проверку config/modules/*.py."""
    called = []
    monkeypatch.setattr(
        ConfigValidator,
        "_validate_config_modules",
        lambda self: called.append(True),
    )

    ConfigValidator().check_config_files()

    assert called, "проверка config/modules/*.py снова стала мёртвым кодом"


def test_broken_nickname_generator_is_only_a_warning():
    """Кривой NICKNAME_GENERATOR не должен ронять запуск всего проекта."""
    validator = ConfigValidator()
    validator._validate_nickname_generator(
        {
            "MIN_LENGTH": 20,
            "MAX_LENGTH": 10,     # меньше MIN_LENGTH
            "USE_SPECIAL_CHARS": "нет",  # не bool
            "QUANTITY": 0,        # не положительное
        }
    )

    assert validator.errors == []
    assert validator.warnings, "проблемы конфига должны быть замечены хотя бы как warning"


def test_nickname_generator_of_wrong_type_is_only_a_warning():
    """NICKNAME_GENERATOR не-словарь — тоже предупреждение, а не error."""
    validator = ConfigValidator()
    validator._validate_nickname_generator("это не словарь")

    assert validator.errors == []
    assert len(validator.warnings) == 1


def test_config_modules_check_adds_no_errors_on_shipped_config():
    """На конфиге из репозитория проверка проходит без критических ошибок."""
    validator = ConfigValidator()
    validator._validate_config_modules()

    assert validator.errors == []


def test_validator_does_not_mention_removed_config_py():
    """config/config.py удалён — валидатор не должен слать пользователя в него."""
    validator = ConfigValidator()
    validator._validate_config_modules()

    joined = " ".join(validator.errors + validator.warnings)
    assert "config/config.py" not in joined
