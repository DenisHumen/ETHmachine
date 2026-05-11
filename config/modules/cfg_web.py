# =============================================================================
# Web Dashboard config
# =============================================================================
# Главный выключатель web-морды живёт в config/modules/general_config.py
# (параметр WEB_ENABLED). Здесь мы только импортируем его, чтобы остальной
# код мог писать `from config.modules.cfg_web import WEB_ENABLED` как раньше.
try:
    from config.modules.general_config import WEB_ENABLED  # noqa: F401
except Exception:
    WEB_ENABLED = True

# Bind адрес. ОСТОРОЖНО: 0.0.0.0 откроет панель в локальной сети без TLS.
WEB_HOST = "127.0.0.1"
WEB_PORT = 8765

# Если False — main.py не будет автоматически поднимать веб-сервер.
WEB_AUTOSTART_FROM_MAIN = True

# Размер in-memory кольцевого буфера логов (сколько последних строк держим
# для новых клиентов веб-морды).
WEB_LOG_RING_SIZE = 2000

# Время жизни сессии в БД (для cookie-авторизации).
WEB_SESSION_TTL_DAYS = 30

# Файл, в котором хранится секрет cookie-подписи (генерируется автоматически).
WEB_COOKIE_SECRET_FILE = "db/.web_cookie_secret"

# Путь к БД с данными web-морды (юзеры/сессии/audit/config_changes/runs).
WEB_DB_PATH = "db/web_admin.db"

# Список config-файлов, изменение которых требует перезапуска main.py.
WEB_RESTART_REQUIRED_PATHS = (
    "config/modules/general_config.py",
    "config/modules/cfg_web.py",
    "config/networks.py",
    "config/menu_config.py",
)
