# 📊 ETHMashine Dashboard Module

Интерактивный терминальный дашборд для мониторинга системы и логирования операций в реальном времени.

## 🎯 Особенности

- ✅ **Легкая интеграция** - всего 3 строки кода
- 📊 **Системный мониторинг** - CPU, RAM, Disk в реальном времени
- 🔍 **Детализация CPU** - общая нагрузка + разбивка по ядрам
- 💾 **Top-10 процессов** по использованию RAM
- 📝 **Расширенный ACTIVITY LOG** (70% экрана)
- 🎨 **Цветовая индикация** нагрузки (зеленый/желтый/красный)
- 🔄 **Обновление в реальном времени**
- 🧵 **Thread-safe** - поддержка многопоточности

## 🚀 Быстрый старт

### Простой запуск

```python
from modules.dashboard.dashboard import ETHMashineDashboard
import curses

dashboard = ETHMashineDashboard()
curses.wrapper(dashboard.draw)
```

### С кастомными данными

```python
dashboard = ETHMashineDashboard(
    custom_logs=[
        {'time': '14:30', 'status': 'success', 'msg': 'Task completed!'}
    ],
    custom_stats={
        'tasks': 150,
        'completed': '147 / 150',
        'success': '98.0%'
    },
    custom_status="My Module Running"
)
curses.wrapper(dashboard.draw)
```

## 📋 API Methods

### `add_log(time_str, status, message, step='')`
Добавить лог в ACTIVITY LOG

```python
dashboard.add_log('14:30', 'success', 'Task completed', '3 of 5')
```

### `update_stats(stats_dict)`
Обновить статистику

```python
dashboard.update_stats({
    'tasks': 150,
    'completed': '147 / 150',
    'success': '98.0%'
})
```

### `update_status(status_text)`
Обновить статус в шапке

```python
dashboard.update_status("Processing Twitter Tasks")
```

## 📊 Структура панелей

```
┌─────────────────────────────────────────────────────┐
│              ETHMashine Dashboard                   │
├──────────────┬──────────────────────────────────────┤
│ SYSTEM INFO  │ ACTIVITY LOG (70% ширины)           │
│ (30%)        │ - Основное окно для ваших логов      │
├──────────────┼──────────────┬───────────────────────┤
│ CPU Usage    │ RAM Usage    │ Peak RAM + Stats      │
│ (40%)        │ (35%)        │ (25%)                 │
│ - Total CPU  │ - System RAM │ - ETHMashine RAM      │
│ - Per Core   │ - Top 10 Proc│ - Custom Stats        │
└──────────────┴──────────────┴───────────────────────┘
```

## 🎨 Доступные статусы для логов

- `success` - ✓ Зеленая галочка
- `error` - ✗ Красный крестик
- `warning` - ⚠ Желтое предупреждение
- `info` - ℹ Информация
- `proving` - ⟳ Символ обработки
- `waiting` - ⏳ Ожидание
- `fetching` - 📥 Получение данных
- `completed` - ✔ Завершено

## 📖 Документация

- **[INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)** - Полное руководство по интеграции
- **[integration_example.py](integration_example.py)** - Примеры использования

## 🔧 Требования

```python
psutil>=5.9.8  # Уже в requirements.txt
curses         # Встроен в Python (Unix) или windows-curses (Windows)
```

## 💡 Примеры интеграции

### Twitter Module

```python
from modules.dashboard.dashboard import ETHMashineDashboard

class TwitterModule:
    def __init__(self):
        self.dashboard = ETHMashineDashboard(
            custom_status="Twitter Task Runner"
        )
    
    def run(self):
        # Ваша логика
        self.dashboard.add_log('14:30', 'success', 'Task completed')
        curses.wrapper(self.dashboard.draw)
```

### OKX Withdraw Module

```python
from modules.dashboard.dashboard import ETHMashineDashboard

class OKXWithdraw:
    def __init__(self):
        self.dashboard = ETHMashineDashboard(
            custom_status="OKX Withdrawal"
        )
    
    def withdraw(self, wallet, amount):
        self.dashboard.add_log('14:30', 'info', f'Withdrawing {amount} to {wallet}')
        # Ваша логика
        self.dashboard.add_log('14:31', 'success', 'Withdrawal completed!')
```

## 🎯 Запуск примеров

```bash
# Стандартный dashboard
python modules/dashboard/dashboard.py

# Примеры интеграции
python modules/dashboard/integration_example.py
```

## 📝 Формат данных

### Логи (activity_logs)

```python
[
    {
        'time': '14:30',          # HH:MM
        'step': '3 of 5',         # Опционально
        'status': 'success',      # См. статусы выше
        'msg': 'Task completed'   # Текст сообщения
    }
]
```

### Статистика (zkvm_stats)

```python
{
    'tasks': 150,                  # Общее количество
    'completed': '147 / 150',      # Выполнено/Всего
    'success': '98.0%',            # Процент успеха
    'runtime': '2h 15m',           # Время работы
    'last': 'Success',             # Последний статус
    'last_proof': '11-04 14:30'    # Последнее время
}
```

## 🌟 Преимущества

1. **Мгновенная интеграция** - 3 строки кода
2. **Real-time мониторинг** - автоматическое обновление системной информации
3. **Расширенный лог** - 70% экрана для ваших логов
4. **CPU детализация** - видно нагрузку на каждое ядро
5. **RAM аналитика** - топ-10 процессов по памяти
6. **Гибкая кастомизация** - собственные логи, статистика, статус

## 📧 Поддержка

Telegram: [@DenisHumen](https://t.me/DenisHumen)

---

**Готово к использованию!** 🚀
