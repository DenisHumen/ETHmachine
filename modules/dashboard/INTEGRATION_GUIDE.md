# 📊 Dashboard Integration Guide

## Быстрый старт

### 1. Простейшая интеграция (1 строка кода)

```python
from modules.dashboard.dashboard import ETHMashineDashboard
import curses

dashboard = ETHMashineDashboard()
curses.wrapper(dashboard.draw)
```

---

## 🔧 API для интеграции

### Инициализация с кастомными данными

```python
dashboard = ETHMashineDashboard(
    custom_logs=your_logs_list,      # Список логов (опционально)
    custom_stats=your_stats_dict,    # Словарь статистики (опционально)
    custom_status="Your Status Text" # Статус в шапке (опционально)
)
```

### Методы для обновления данных в реальном времени

#### 1. Добавление логов

```python
dashboard.add_log(
    time_str='14:30',           # Время в формате HH:MM
    status='success',            # success, error, warning, info, proving, waiting, etc.
    message='Task completed',    # Текст сообщения
    step='3 of 5'               # Опционально: шаг выполнения
)
```

**Доступные статусы:**
- `success` - Зеленая галочка ✓
- `error` - Красный крестик
- `warning` - Желтое предупреждение
- `info` - Информация
- `proving` - Символ обработки ⟳
- `waiting` - Ожидание
- `fetching` - Получение данных
- `completed` - Завершено

#### 2. Обновление статистики

```python
dashboard.update_stats({
    'tasks': 150,
    'completed': '147 / 150',
    'success': '98.0%',
    'runtime': '2h 15m',
    'last': 'Success',
    'last_proof': '11-04 14:30'
})
```

#### 3. Обновление статуса в шапке

```python
dashboard.update_status("Processing Twitter Tasks")
```

---

## 📝 Примеры интеграции

### Пример 1: Twitter модуль

```python
from modules.dashboard.dashboard import ETHMashineDashboard
from datetime import datetime
import curses

class TwitterTaskRunner:
    def __init__(self):
        self.dashboard = ETHMashineDashboard(
            custom_status="Twitter Task Runner"
        )
    
    def process_account(self, account_name):
        current_time = datetime.now().strftime("%H:%M")
        
        # Логируем начало
        self.dashboard.add_log(current_time, 'info', f'Processing @{account_name}', '1 of 3')
        
        # Выполняем действия
        self.do_like()
        self.dashboard.add_log(current_time, 'success', f'Liked tweet from @{account_name}', '2 of 3')
        
        self.do_retweet()
        self.dashboard.add_log(current_time, 'success', f'Retweeted from @{account_name}', '3 of 3')
        
        # Обновляем статистику
        self.dashboard.update_stats({
            'tasks': self.total_tasks,
            'completed': f'{self.completed_tasks} / {self.total_tasks}',
            'success': f'{(self.completed_tasks/self.total_tasks*100):.1f}%'
        })
    
    def run(self):
        curses.wrapper(self.dashboard.draw)
```

### Пример 2: OKX Withdraw модуль

```python
from modules.dashboard.dashboard import ETHMashineDashboard
from datetime import datetime
import curses

class OKXWithdraw:
    def __init__(self):
        self.dashboard = ETHMashineDashboard(
            custom_status="OKX Withdrawal in Progress"
        )
    
    def withdraw(self, wallet, amount):
        current_time = datetime.now().strftime("%H:%M")
        
        # Логируем вывод
        self.dashboard.add_log(
            current_time, 
            'info', 
            f'Initiating withdrawal to {wallet[:8]}... Amount: {amount} USDT',
            '1 of 4'
        )
        
        # Проверка баланса
        if self.check_balance(amount):
            self.dashboard.add_log(current_time, 'success', 'Balance verified', '2 of 4')
        else:
            self.dashboard.add_log(current_time, 'error', 'Insufficient balance', '')
            return
        
        # Создание заказа
        self.dashboard.add_log(current_time, 'info', 'Creating withdrawal order...', '3 of 4')
        order_id = self.create_withdrawal_order(wallet, amount)
        
        self.dashboard.add_log(
            current_time, 
            'success', 
            f'Withdrawal successful! Order ID: {order_id}',
            '4 of 4'
        )
        
        # Обновляем статистику
        self.dashboard.update_stats({
            'tasks': self.total_withdrawals,
            'completed': f'{self.completed_withdrawals} / {self.total_withdrawals}',
            'success': f'{self.success_rate:.1f}%',
            'runtime': self.get_runtime()
        })
    
    def run(self):
        curses.wrapper(self.dashboard.draw)
```

### Пример 3: Фоновая задача с дашбордом

```python
import threading
import time
from datetime import datetime
from modules.dashboard.dashboard import ETHMashineDashboard
import curses

class BackgroundTaskWithDashboard:
    def __init__(self):
        self.dashboard = ETHMashineDashboard(custom_status="Background Task Running")
        self.running = True
    
    def background_worker(self):
        """Фоновая задача обновляет дашборд"""
        task_count = 0
        while self.running:
            task_count += 1
            current_time = datetime.now().strftime("%H:%M")
            
            # Добавляем логи
            self.dashboard.add_log(
                current_time, 
                'success', 
                f'Processed background task #{task_count}'
            )
            
            # Обновляем статистику каждые 5 задач
            if task_count % 5 == 0:
                self.dashboard.update_stats({
                    'tasks': task_count,
                    'completed': f'{task_count} / {task_count}',
                    'success': '100%'
                })
            
            time.sleep(2)
    
    def run(self):
        # Запускаем фоновую задачу
        worker_thread = threading.Thread(target=self.background_worker, daemon=True)
        worker_thread.start()
        
        # Запускаем дашборд
        try:
            curses.wrapper(self.dashboard.draw)
        finally:
            self.running = False

# Использование
task = BackgroundTaskWithDashboard()
task.run()
```

---

## 🎨 Структура дашборда

### Панели дашборда:

```
┌─────────────────────────────────────────────────────────────────┐
│                    ETHMashine v3.10.0                           │
│                                                                 │
│ PROVING - Your Status Text                                     │
│                                                                 │
├─────────────────┬───────────────────────────────────────────────┤
│ SYSTEM INFO     │ ACTIVITY LOG (70% ширины)                    │
│ (30% ширины)    │                                               │
│                 │ ✓ 14:30: Task completed                       │
│ Node: PC-NAME   │ ⟳ 14:29: Processing...                        │
│ OS: Windows 11  │ ℹ 14:28: Fetching data                        │
│ Python: 3.10.0  │ ...                                           │
│ Uptime: 2h 15m  │                                               │
│ CPU: 8C/16T     │                                               │
│ RAM: 16GB       │                                               │
│ Disk: 500GB     │                                               │
├─────────────────┼───────────────┬───────────────────────────────┤
│ CPU Usage       │ RAM Usage     │ Peak RAM (ETHMashine)         │
│ (40%)           │ (35%)         │ zkVM STATS (25%)              │
│                 │               │                               │
│ ═══ TOTAL ═══   │ ═══ SYSTEM ═══│ 245.7 MB                      │
│    45.2%        │ 8192MB / 16GB │ ████████░░                    │
│ ████████░░░     │ ████████░░    │                               │
│ ──────────────  │ ──────────────│ Tasks: 150                    │
│ Per Core:       │ Top 10:       │ Completed: 147/150            │
│ C0: 23.1%       │ 1. chrome 500M│ Success: 98.0%                │
│ C1: 67.8%       │ 2. python 245M│                               │
│ ...             │ ...           │                               │
└─────────────────┴───────────────┴───────────────────────────────┘
```

### Особенности:

1. **SYSTEM INFO (30%)** - Компактная системная информация
2. **ACTIVITY LOG (70%)** - Основное окно для логов вашего модуля
3. **CPU Usage (40%)** - Полная нагрузка + разбивка по ядрам
4. **RAM Usage (35%)** - Общая память + топ-10 процессов
5. **Peak RAM** - Пиковое использование памяти вашим процессом
6. **zkVM STATS** - Кастомная статистика вашего модуля

---

## 🚀 Быстрая интеграция (одна функция)

```python
from modules.dashboard.dashboard import ETHMashineDashboard
import curses

def run_with_dashboard(logs=None, stats=None, status=None):
    """Быстрый запуск дашборда"""
    dashboard = ETHMashineDashboard(
        custom_logs=logs,
        custom_stats=stats,
        custom_status=status
    )
    curses.wrapper(dashboard.draw)

# Использование в вашем модуле:
run_with_dashboard(
    logs=[{'time': '14:30', 'status': 'success', 'msg': 'Done!'}],
    status="My Module"
)
```

---

## 📊 Формат данных

### Формат логов (activity_logs):

```python
[
    {
        'time': '14:30',          # Время (строка HH:MM)
        'step': '3 of 5',         # Шаг выполнения (опционально)
        'status': 'success',      # Статус (success, error, info, etc.)
        'msg': 'Task completed'   # Сообщение
    },
    # ... больше логов
]
```

### Формат статистики (zkvm_stats):

```python
{
    'tasks': 150,                  # Общее количество задач
    'completed': '147 / 150',      # Выполнено/Всего
    'success': '98.0%',            # Процент успеха
    'runtime': '2h 15m',           # Время работы
    'last': 'Success',             # Последний статус
    'last_proof': '11-04 14:30'    # Последнее время
}
```

---

## 💡 Советы по интеграции

1. **Создавайте дашборд в `__init__`** вашего класса
2. **Используйте `add_log()`** для добавления логов в процессе работы
3. **Обновляйте `update_stats()`** после каждой задачи
4. **Используйте `update_status()`** для изменения статуса в шапке
5. **Запускайте `curses.wrapper(dashboard.draw)`** в конце

---

## 🔍 Примеры использования в ETHmachine

Смотрите полные примеры в файле `integration_example.py`

```bash
python modules/dashboard/integration_example.py
```

---

**Готово!** Теперь вы можете легко интегрировать дашборд в любой модуль ETHmachine! 🎉
