"""
Captcha Manager - централизованное управление решением капчи.

Поддерживаемые сервисы: 2captcha, anticaptcha, capsolver, yescaptcha, capmonster
Поддерживаемые типы капчи: hcaptcha, turnstile, recaptcha_v2, recaptcha_v3
"""
from typing import Optional
from modules.simple_logger import logger

from config.modules.cfg_base import (
    CAPTCHA_SERVICE,
    TWOCAPTCHA_API_KEY,
    ANTICAPTCHA_API_KEY,
    CAPSOLVER_API_KEY,
    YESCAPTCHA_API_KEY,
    CAPMONSTER_API_KEY,
    MAIN_PROXY,
)

# Какие типы капчи поддерживает каждый сервис
SERVICE_CAPABILITIES = {
    '2captcha':    ['hcaptcha', 'turnstile', 'recaptcha_v2', 'recaptcha_v3'],
    'anticaptcha': ['hcaptcha', 'turnstile', 'recaptcha_v2', 'recaptcha_v3'],
    'capsolver':   ['hcaptcha', 'turnstile', 'recaptcha_v2', 'recaptcha_v3'],
    'yescaptcha':  ['hcaptcha', 'turnstile', 'recaptcha_v2', 'recaptcha_v3'],
    'capmonster':  ['hcaptcha', 'turnstile', 'recaptcha_v2', 'recaptcha_v3'],
}

# Маппинг сервис -> API ключ
_SERVICE_KEYS = {
    '2captcha':    lambda: TWOCAPTCHA_API_KEY,
    'anticaptcha': lambda: ANTICAPTCHA_API_KEY,
    'capsolver':   lambda: CAPSOLVER_API_KEY,
    'yescaptcha':  lambda: YESCAPTCHA_API_KEY,
    'capmonster':  lambda: CAPMONSTER_API_KEY,
}


def _get_service_names():
    return ', '.join(f"'{s}'" for s in SERVICE_CAPABILITIES)


def check_captcha_support(service: str, captcha_type: str) -> bool:
    """Проверяет, поддерживает ли сервис данный тип капчи."""
    caps = SERVICE_CAPABILITIES.get(service, [])
    if captcha_type in caps:
        return True

    suitable = [s for s, types in SERVICE_CAPABILITIES.items() if captcha_type in types]
    logger.warning(
        f"[Captcha] Сервис '{service}' не поддерживает тип '{captcha_type}'. "
        f"Подходящие сервисы: {', '.join(suitable) if suitable else 'нет'}"
    )
    return False


def _create_solver(service: str, api_key: str, proxy: Optional[str] = None):
    """Создаёт экземпляр solver для указанного сервиса."""
    if service == '2captcha':
        from modules.captcha.solver_2captcha import TwoCaptchaSolver
        return TwoCaptchaSolver(api_key=api_key, proxy=proxy)
    elif service == 'anticaptcha':
        from modules.captcha.solver_anticaptcha import AntiCaptchaSolver
        return AntiCaptchaSolver(api_key=api_key, proxy=proxy)
    elif service == 'capsolver':
        from modules.captcha.solver_capsolver import CapsolverSolver
        return CapsolverSolver(api_key=api_key, proxy=proxy)
    elif service == 'yescaptcha':
        from modules.captcha.solver_yescaptcha import YesCaptchaSolver
        return YesCaptchaSolver(api_key=api_key, proxy=proxy)
    elif service == 'capmonster':
        from modules.captcha.solver_capmonster import CapMonsterSolver
        return CapMonsterSolver(api_key=api_key, proxy=proxy)
    else:
        raise ValueError(f"Неизвестный сервис капчи: '{service}'. Доступные: {_get_service_names()}")


def get_captcha_solver(proxy_url: Optional[str] = None):
    """
    Получить solver капчи на основе конфига.
    Приоритет: CAPTCHA_SERVICE из конфига -> fallback по наличию ключей.
    """
    captcha_proxy = proxy_url or (MAIN_PROXY if MAIN_PROXY else None)

    # Приоритет: выбранный в конфиге сервис
    service = CAPTCHA_SERVICE
    key_getter = _SERVICE_KEYS.get(service)
    if key_getter:
        api_key = key_getter()
        if api_key:
            return _create_solver(service, api_key, captcha_proxy)

    # Fallback: первый доступный сервис с ключом
    for svc, key_fn in _SERVICE_KEYS.items():
        api_key = key_fn()
        if api_key:
            logger.info(f"[Captcha] Сервис '{service}' не настроен, используем '{svc}' как fallback")
            return _create_solver(svc, api_key, captcha_proxy)

    logger.warning("[Captcha] Ни один сервис капчи не настроен (нет API ключей)")
    return None


class CaptchaManager:
    """Менеджер капчи с проверкой совместимости и автоматическим выбором solver."""

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy
        self._solver = None
        self._service = CAPTCHA_SERVICE
        self._init_solver()

    def _init_solver(self):
        try:
            self._solver = get_captcha_solver(self.proxy)
        except Exception as e:
            logger.warning(f"[CaptchaManager] Не удалось инициализировать solver: {e}")

    @property
    def solver(self):
        return self._solver

    @property
    def is_available(self) -> bool:
        return self._solver is not None

    def solve_hcaptcha(self, sitekey: str, pageurl: str,
                       user_agent: Optional[str] = None,
                       is_invisible: bool = False) -> Optional[str]:
        if not self._check_and_warn('hcaptcha'):
            return None
        return self._solver.solve_hcaptcha(
            sitekey=sitekey, pageurl=pageurl,
            user_agent=user_agent, is_invisible=is_invisible,
        )

    def solve_turnstile(self, sitekey: str, pageurl: str,
                        action: Optional[str] = None,
                        user_agent: Optional[str] = None) -> Optional[str]:
        if not self._check_and_warn('turnstile'):
            return None
        return self._solver.solve_turnstile(
            sitekey=sitekey, pageurl=pageurl,
            action=action, user_agent=user_agent,
        )

    def solve_recaptcha_v2(self, sitekey: str, pageurl: str,
                           is_invisible: bool = False) -> Optional[str]:
        if not self._check_and_warn('recaptcha_v2'):
            return None
        return self._solver.solve_recaptcha_v2(
            sitekey=sitekey, pageurl=pageurl,
            is_invisible=is_invisible,
        )

    def solve_recaptcha_v3(self, sitekey: str, pageurl: str,
                           page_action: str = "",
                           min_score: float = 0.3) -> Optional[str]:
        if not self._check_and_warn('recaptcha_v3'):
            return None
        return self._solver.solve_recaptcha_v3(
            sitekey=sitekey, pageurl=pageurl,
            page_action=page_action, min_score=min_score,
        )

    def _check_and_warn(self, captcha_type: str) -> bool:
        if not self._solver:
            logger.error("[CaptchaManager] Solver не инициализирован. Настройте API ключ в cfg_base.py")
            return False
        return check_captcha_support(self._service, captcha_type)

    @property
    def session_stats(self) -> dict:
        if self._solver and hasattr(self._solver, 'session_stats'):
            return self._solver.session_stats
        return {"solves": 0, "points_spent": 0, "usdt_spent": 0}
