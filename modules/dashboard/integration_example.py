#!/usr/bin/env python3
"""
Пример интеграции дашборда в существующий модуль

Этот файл показывает, как легко интегрировать dashboard в любой другой модуль
"""

import curses
import time
from datetime import datetime
from dashboard import ETHMashineDashboard

# ========================================
# Пример 1: Простая интеграция
# ========================================

def simple_integration_example():
    """Простейший пример - запуск дашборда с дефолтными данными"""
    dashboard = ETHMashineDashboard()
    curses.wrapper(dashboard.draw)


# ========================================
# Пример 2: Интеграция с кастомными логами
# ========================================

def custom_logs_example():
    """Пример с передачей собственных логов"""
    
    # Подготовка собственных логов
    my_logs = [
        {'time': '14:30', 'step': '', 'status': 'success', 'msg': 'Twitter task completed successfully'},
        {'time': '14:29', 'step': '3 of 3', 'status': 'proving', 'msg': 'Processing account @user123'},
        {'time': '14:28', 'step': '2 of 3', 'status': 'info', 'msg': 'Fetching tweets from timeline'},
        {'time': '14:27', 'step': '1 of 3', 'status': 'waiting', 'msg': 'Waiting for rate limit reset'},
    ]
    
    # Кастомная статистика
    my_stats = {
        'tasks': 150,
        'completed': '147 / 150',
        'success': '98.0%',
        'runtime': '2h 15m',
        'last': 'Success',
        'last_proof': '11-04 14:30'
    }
    
    # Создание дашборда с кастомными данными
    dashboard = ETHMashineDashboard(
        custom_logs=my_logs,
        custom_stats=my_stats,
        custom_status="Processing Twitter Tasks"
    )
    
    curses.wrapper(dashboard.draw)


# ========================================
# Пример 3: Интеграция в существующий модуль с обновлением в реальном времени
# ========================================

class MyModule:
    """Пример класса модуля с интеграцией дашборда"""
    
    def __init__(self):
        self.dashboard = None
        self.is_running = False
    
    def process_task(self, task_id):
        """Обработка задачи с логированием в дашборд"""
        if self.dashboard:
            # Добавляем лог о начале задачи
            current_time = datetime.now().strftime("%H:%M")
            self.dashboard.add_log(current_time, 'info', f'Starting task {task_id}', '1 of 3')
            
            # Симуляция работы
            time.sleep(1)
            
            # Добавляем лог об успехе
            self.dashboard.add_log(current_time, 'success', f'Task {task_id} completed', '3 of 3')
            
            # Обновляем статистику
            self.dashboard.update_stats({
                'tasks': 10,
                'completed': '8 / 10',
                'success': '80.0%'
            })
    
    def run_with_dashboard(self):
        """Запуск модуля с дашбордом"""
        # Создаем дашборд
        self.dashboard = ETHMashineDashboard(
            custom_status="My Module Running"
        )
        
        # Добавляем начальные логи
        self.dashboard.add_log('14:35', 'info', 'Module started')
        
        # Запускаем дашборд
        curses.wrapper(self.dashboard.draw)


# ========================================
# Пример 4: Интеграция с фоновой задачей
# ========================================

import threading

class BackgroundTaskWithDashboard:
    """Пример запуска фоновой задачи с дашбордом"""
    
    def __init__(self):
        self.dashboard = ETHMashineDashboard(custom_status="Background Task Running")
        self.running = True
    
    def background_worker(self):
        """Фоновая задача, которая обновляет дашборд"""
        task_count = 0
        while self.running:
            task_count += 1
            current_time = datetime.now().strftime("%H:%M")
            
            # Добавляем логи в дашборд
            if self.dashboard:
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
        """Запуск с фоновой задачей"""
        # Запускаем фоновую задачу в отдельном потоке
        worker_thread = threading.Thread(target=self.background_worker, daemon=True)
        worker_thread.start()
        
        # Запускаем дашборд в основном потоке
        try:
            curses.wrapper(self.dashboard.draw)
        finally:
            self.running = False


# ========================================
# Пример 5: API для быстрой интеграции
# ========================================

def quick_integration(logs=None, stats=None, status=None):
    """
    Быстрый способ запустить дашборд из любого модуля
    
    Args:
        logs: Список логов или None для дефолтных
        stats: Словарь статистики или None для дефолтных
        status: Строка статуса или None для дефолтного
    
    Example:
        from modules.dashboard.integration_example import quick_integration
        
        quick_integration(
            logs=[{'time': '14:30', 'status': 'success', 'msg': 'Done!'}],
            status="My Module"
        )
    """
    dashboard = ETHMashineDashboard(
        custom_logs=logs,
        custom_stats=stats,
        custom_status=status
    )
    curses.wrapper(dashboard.draw)


# ========================================
# Главная функция для демонстрации
# ========================================

if __name__ == '__main__':
    print("Примеры интеграции дашборда:")
    print("1. Простая интеграция (дефолтные данные)")
    print("2. С кастомными логами и статистикой")
    print("3. Интеграция в класс модуля")
    print("4. С фоновой задачей")
    print("5. Быстрая интеграция (одна строка)")
    
    choice = input("\nВыберите пример (1-5): ")
    
    if choice == '1':
        simple_integration_example()
    elif choice == '2':
        custom_logs_example()
    elif choice == '3':
        module = MyModule()
        module.run_with_dashboard()
    elif choice == '4':
        bg_task = BackgroundTaskWithDashboard()
        bg_task.run()
    elif choice == '5':
        quick_integration(
            logs=[
                {'time': '14:30', 'step': '', 'status': 'success', 'msg': 'Quick integration example!'},
                {'time': '14:29', 'step': '', 'status': 'info', 'msg': 'This is very easy to use'},
            ],
            status="Quick Integration Test"
        )
    else:
        print("Неверный выбор!")
