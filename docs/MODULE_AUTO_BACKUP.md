# � Модуль управления бэкапами

Комплексный модуль для создания, управления и восстановления бэкапов с поддержкой локального хранения и SFTP сервера.

## � Содержание

- [Возможности](#возможности)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Конфигурация](#конфигурация)
- [Использование через меню](#использование-через-меню)
- [Использование в коде](#использование-в-коде)
- [SFTP настройка](#sftp-настройка)
- [API документация](#api-документация)
- [Решение проблем](#решение-проблем)

---

## 🎯 Возможности

### Локальные бэкапы
- ✅ Создание ZIP архивов
- ✅ Автоматическая очистка старых бэкапов
- ✅ Восстановление из бэкапа
- ✅ Просмотр списка бэкапов
- ✅ Настраиваемые директории для бэкапа

### SFTP бэкапы
- ✅ Загрузка на SFTP сервер
- ✅ Скачивание с SFTP сервера
- ✅ Авторизация по паролю или SSH ключу
- ✅ Автоматическая очистка старых бэкапов на сервере
- ✅ Тестирование подключения
- ✅ Включение/выключение через меню

### Общие возможности
- ✅ Интерактивное меню управления
- ✅ Подробное логирование
- ✅ Цветной вывод в консоль
- ✅ Индикация размера архивов
- ✅ Настраиваемое количество хранимых бэкапов

---

## 📦 Установка

### Основной функционал (локальные бэкапы)
Работает без дополнительных зависимостей.

### SFTP функционал
Требуется установка paramiko:

```bash
pip install paramiko
```

Или установите все зависимости проекта:

```bash
pip install -r requirements.txt
```

---

## 🚀 Быстрый старт

### 1. Через главное меню

```bash
python main.py
```

В главном меню выберите: **💾 Управление бэкапами**

### 2. Создание простого бэкапа

```python
from modules.backup import BackupManager

manager = BackupManager()
manager.create_backup()
```

### 3. Восстановление последнего бэкапа

```python
from modules.backup import BackupManager

manager = BackupManager()
manager.restore_local_backup()  # Восстановит последний бэкап
```

---

## ⚙️ Конфигурация

Настройки находятся в `config/config.py`:

### Основные параметры

```python
# Максимальное количество хранимых бэкапов
MAX_BACKUPS_TO_KEEP = 3

# Директории для включения в бэкап
DIRECTORIES_TO_BACKUP = [
    'data',
    'db',
    'result'
]
```

### SFTP конфигурация

```python
# Включение/выключение SFTP бэкапа
SFTP_SERVER_INTO_BACKUP_ENABLE = True

# Настройки SFTP сервера
SFTP_SERVER_INTO_BACKUP = {
    'host': 'sftp.example.com',      # Адрес SFTP сервера
    'port': 22,                       # Порт (обычно 22)
    'username': 'your_username',      # Имя пользователя
    'password': 'your_password',      # Пароль (если используется)
    'key_file': '/path/to/id_rsa',   # Путь к SSH ключу (приоритет над паролем)
    'remote_path': '/backups/'        # Путь для хранения бэкапов на сервере
}
```

#### Варианты авторизации

**1. По паролю:**
```python
SFTP_SERVER_INTO_BACKUP = {
    'host': 'sftp.example.com',
    'port': 22,
    'username': 'user',
    'password': 'secret_password',
    'key_file': '',
    'remote_path': '/backups/'
}
```

**2. По SSH ключу (рекомендуется):**
```python
SFTP_SERVER_INTO_BACKUP = {
    'host': 'sftp.example.com',
    'port': 22,
    'username': 'user',
    'password': '',
    'key_file': '/home/user/.ssh/id_rsa',
    'remote_path': '/backups/'
}
```

---

## 📱 Использование через меню

### Доступ к меню

```bash
python main.py
# → 💾 Управление бэкапами
```

### Опции меню

**Локальные бэкапы:**
- 📦 Создать бэкап
- 📋 Показать локальные бэкапы
- 🔄 Восстановить из локального бэкапа
- 🧹 Очистить старые локальные бэкапы

**SFTP бэкапы (если включены):**
- ☁️  Показать SFTP бэкапы
- ⬇️ Скачать бэкап с SFTP
- 🔄 Восстановить из SFTP бэкапа
- 🧹 Очистить старые SFTP бэкапы
- 🧪 Тест подключения к SFTP
- ⚙️  Включить/Выключить SFTP бэкап

---

## 💻 Использование в коде

### Создание менеджера

```python
from modules.backup import BackupManager

manager = BackupManager()
```

### Локальные операции

```python
# Создать локальный бэкап
backup_path = manager.create_local_backup()

# Показать список локальных бэкапов
manager.show_local_backups_info()

# Получить список имен файлов
backups = manager.list_local_backups()

# Восстановить последний бэкап
manager.restore_local_backup()

# Восстановить конкретный бэкап
manager.restore_local_backup('backup_20241015_123456.zip')

# Очистить старые бэкапы
manager.cleanup_old_local_backups()
```

### SFTP операции

```python
# Проверка доступности SFTP
if manager.sftp_enabled:
    print("SFTP доступен")

# Тест подключения
manager.test_sftp_connection()

# Загрузить файл на SFTP
manager.upload_to_sftp('/path/to/backup.zip')

# Показать SFTP бэкапы
manager.show_sftp_backups_info()

# Получить список SFTP бэкапов
sftp_backups = manager.list_sftp_backups()

# Скачать последний бэкап
manager.download_from_sftp()

# Скачать конкретный бэкап
manager.download_from_sftp('backup_20241015_123456.zip')

# Очистить старые SFTP бэкапы
manager.cleanup_old_sftp_backups()
```

### 📊 Прогресс-бар передачи SFTP

При загрузке и скачивании файлов через SFTP автоматически отображается прогресс-бар в стиле Ubuntu:

**Отображаемая информация:**

- 📊 Визуальный прогресс-бар (50 символов)
- 📈 Процент выполнения
- 📦 Переданный объем / Общий объем
- ⚡ Скорость передачи (MB/s или KB/s)
- ⏱️ Оставшееся время (ETA)
- ⏳ Прошедшее время

**Пример отображения:**

```text
backup_20250118.zip            [████████████████░░░░░░░░░░░░░░] 45.3%  125.43MB/ 276.89MB    12.34MB/s ETA: 00:12 Elapsed: 00:10
```

**Особенности:**

- Автоматическое усреднение скорости для плавности
- Обновление не чаще 0.1 секунды (оптимизация производительности)
- Автоматическое определение единиц измерения (B/KB/MB/GB/TB)
- Адаптивное форматирование времени (ММ:СС или ЧЧ:ММ:СС)
- Не использует внешние библиотеки (чистый Python)

**Технические детали:**

- Реализация: класс `SFTPProgressBar` в `modules/backup/backup_manager.py`
- Использует callback механизм paramiko
- Совместим с методами `sftp.put()` и `sftp.get()`
- Автоматически срабатывает при любой SFTP передаче

### Комплексные операции

```python
# Создать бэкап и загрузить на SFTP
manager.create_backup(upload_to_sftp=True)

# Создать только локальный бэкап
manager.create_backup(upload_to_sftp=False)

# Скачать с SFTP и восстановить
if manager.download_from_sftp():
    manager.restore_local_backup()
```

---

## 🔐 SFTP настройка

### Создание SSH ключа

**Linux/Mac:**
```bash
# Генерация ключа
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"

# Копирование на сервер
ssh-copy-id user@sftp-server.com

# Установка правильных прав
chmod 600 ~/.ssh/id_rsa
chmod 700 ~/.ssh
```

**Windows (PowerShell):**
```powershell
# Генерация ключа
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"

# Копирование публичного ключа на сервер
type $env:USERPROFILE\.ssh\id_rsa.pub | ssh user@sftp-server.com "cat >> .ssh/authorized_keys"
```

### Тестирование SSH подключения

```bash
# Тест SSH
ssh -i ~/.ssh/id_rsa user@sftp-server.com

# Тест SFTP
sftp -i ~/.ssh/id_rsa user@sftp-server.com
```

### Включение/выключение SFTP через меню

1. Откройте меню бэкапов
2. Выберите "⚙️  Настроить SFTP бэкап"
3. Выберите "✅ Включить" или "❌ Выключить"
4. При включении автоматически выполнится тест подключения

При включении через меню параметр `SFTP_SERVER_INTO_BACKUP_ENABLE` автоматически изменится в `config/config.py`.

---

## 📚 API документация

### Класс BackupManager

```python
from modules.backup import BackupManager
```

#### Инициализация

```python
manager = BackupManager()
```

**Атрибуты:**
- `project_root` - Корневая директория проекта
- `backup_local_dir` - Директория локальных бэкапов
- `sftp_config` - Конфигурация SFTP
- `sftp_enabled` - Доступность SFTP функций

#### Методы локальных бэкапов

**create_local_backup() -> Optional[str]**
- Создает локальный ZIP архив
- Возвращает путь к архиву или None при ошибке

**list_local_backups() -> List[str]**
- Возвращает список имен файлов бэкапов
- Сортировка: новые первыми

**show_local_backups_info()**
- Выводит подробную информацию о локальных бэкапах
- Показывает размер и дату создания

**restore_local_backup(backup_name: Optional[str] = None) -> bool**
- Восстанавливает данные из бэкапа
- Если backup_name не указан, использует последний
- Возвращает True при успехе

**cleanup_old_local_backups()**
- Удаляет старые бэкапы
- Оставляет количество согласно MAX_BACKUPS_TO_KEEP

#### Методы SFTP бэкапов

**test_sftp_connection() -> bool**
- Тестирует подключение к SFTP серверу
- Возвращает True при успехе

**upload_to_sftp(local_file: str) -> bool**
- Загружает файл на SFTP сервер
- Возвращает True при успехе

**list_sftp_backups() -> List[str]**
- Возвращает список бэкапов на SFTP сервере
- Сортировка: новые первыми

**show_sftp_backups_info()**
- Выводит подробную информацию о SFTP бэкапах

**download_from_sftp(backup_name: Optional[str] = None) -> bool**
- Скачивает бэкап с SFTP сервера
- Если backup_name не указан, скачивает последний
- Возвращает True при успехе

**cleanup_old_sftp_backups()**
- Удаляет старые бэкапы на SFTP сервере
- Оставляет количество согласно MAX_BACKUPS_TO_KEEP

#### Универсальные методы

**create_backup(upload_to_sftp: bool = True) -> bool**
- Создает локальный бэкап
- Опционально загружает на SFTP
- Автоматически очищает старые бэкапы
- Возвращает True при успехе

### Функции для совместимости

```python
from modules.backup import create_backup, list_backups

# Создать бэкап (старый API)
create_backup()

# Показать список бэкапов (старый API)
list_backups()
```

### Меню

```python
from modules.backup import backup_menu

# Запустить интерактивное меню
backup_menu()
```

---

## 🐛 Решение проблем

### Проблема: "No module named 'paramiko'"

**Решение:**
```bash
pip install paramiko
```

SFTP функции будут работать только после установки paramiko.

### Проблема: "Permission denied (publickey)"

**Возможные причины:**
1. Публичный ключ не добавлен на сервер
2. Неправильные права доступа к файлу ключа
3. Неверный путь к ключу в config.py

**Решение:**
```bash
# Проверьте права на ключ
chmod 600 ~/.ssh/id_rsa
chmod 700 ~/.ssh

# Добавьте ключ на сервер
ssh-copy-id user@sftp-server.com

# Проверьте путь в config.py
'key_file': '/home/user/.ssh/id_rsa'  # Должен быть полный путь
```

### Проблема: "Connection refused"

**Возможные причины:**
1. SFTP сервер не запущен
2. Порт закрыт firewall
3. Неверный адрес или порт

**Решение:**
```bash
# Проверьте доступность сервера
ping sftp-server.com

# Проверьте порт
telnet sftp-server.com 22

# Проверьте настройки в config.py
'host': 'sftp-server.com',
'port': 22,
```

### Проблема: "Authentication failed"

**Решение:**
1. Проверьте правильность логина и пароля
2. Убедитесь, что используете правильный метод авторизации
3. Если используете ключ, убедитесь что он правильный
4. Проверьте, что пользователь имеет права на SFTP

### Проблема: "No such file or directory" (на сервере)

**Решение:**
```bash
# Убедитесь, что директория существует на сервере
ssh user@sftp-server.com "mkdir -p /backups"

# Или измените путь в config.py на существующую директорию
'remote_path': '/home/user/backups/'
```

### Проблема: Бэкап не создается

**Проверьте:**
1. Права доступа к директории backups/
2. Свободное место на диске
3. Логи в log/backup.log
4. Существование директорий из DIRECTORIES_TO_BACKUP

### Проблема: SFTP бэкап не включается через меню

**Решение:**
1. Убедитесь, что все параметры заполнены в config.py
2. Проверьте подключение через "Тест подключения"
3. Проверьте логи в log/backup.log

---

## 📊 Структура модуля

```
modules/backup/
├── __init__.py              # Экспорты модуля
├── backup_manager.py        # Основной класс BackupManager
└── menu.py                  # Интерактивное меню

docs/
└── MODULE_AUTO_BACKUP.md    # Эта документация

backups/                     # Директория локальных бэкапов
├── backup_20241015_120000.zip
├── backup_20241015_130000.zip
└── backup_20241015_140000.zip

log/
└── backup.log               # Логи модуля
```

---

## 📝 Примеры использования

### Пример 1: Автоматический бэкап при запуске приложения

```python
from modules.backup import BackupManager

def startup():
    # Создаем бэкап при запуске
    manager = BackupManager()
    manager.create_backup()
    
    # Ваш код приложения
    ...
```

### Пример 2: Бэкап перед критической операцией

```python
from modules.backup import BackupManager

def dangerous_operation():
    # Создаем бэкап перед опасной операцией
    manager = BackupManager()
    backup_path = manager.create_local_backup()
    
    try:
        # Выполняем операцию
        perform_risky_task()
    except Exception as e:
        # При ошибке восстанавливаем
        manager.restore_local_backup(os.path.basename(backup_path))
        raise
```

### Пример 3: Регулярный бэкап (cron)

```bash
# Linux/Mac - добавьте в crontab
0 2 * * * cd /path/to/ETHmachine && python3 -c "from modules.backup import BackupManager; BackupManager().create_backup()"
```

### Пример 4: Условный бэкап на SFTP

```python
from modules.backup import BackupManager

manager = BackupManager()

# Создаем локальный бэкап
backup_path = manager.create_local_backup()

# Загружаем на SFTP только если это важный бэкап
if is_important_backup():
    if manager.sftp_enabled:
        manager.upload_to_sftp(backup_path)
```

### Пример 5: Синхронизация с SFTP

```python
from modules.backup import BackupManager

def sync_with_sftp():
    manager = BackupManager()
    
    if not manager.sftp_enabled:
        print("SFTP не настроен")
        return
    
    # Получаем списки
    local_backups = set(manager.list_local_backups())
    sftp_backups = set(manager.list_sftp_backups())
    
    # Загружаем отсутствующие на сервере
    for backup in local_backups - sftp_backups:
        backup_path = os.path.join(manager.backup_local_dir, backup)
        manager.upload_to_sftp(backup_path)
    
    # Скачиваем отсутствующие локально
    for backup in sftp_backups - local_backups:
        manager.download_from_sftp(backup)
```

---

## 🔒 Безопасность

### Рекомендации:

1. **Используйте SSH ключи** вместо паролей
2. **Не коммитьте config.py** с реальными данными в Git
3. **Ограничьте права доступа** к файлу ключа:
   ```bash
   chmod 600 ~/.ssh/id_rsa
   ```
4. **Используйте отдельного пользователя** на SFTP сервере с ограниченными правами
5. **Настройте firewall** для доступа только с вашего IP
6. **Регулярно обновляйте** paramiko и другие зависимости
7. **Проверяйте логи** на подозрительную активность

### Файл .gitignore

Убедитесь, что в `.gitignore` есть:
```
config/config.py
backups/
log/
*.zip
```

---

## � Поддержка

При возникновении проблем:

1. Проверьте логи в `log/backup.log`
2. Запустите тест подключения через меню
3. Убедитесь, что все настройки указаны корректно
4. Проверьте доступность SFTP сервера

---

## 📄 Лицензия

Модуль является частью проекта ETHmachine.

**Создано:** 15 октября 2025  
**Версия:** 2.0.0  
**Автор:** GitHub Copilot
