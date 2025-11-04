#!/usr/bin/env python3

import curses
import time
import psutil
import platform
import socket
from datetime import datetime, timedelta
from typing import List, Dict, Any

class ETHMashineDashboard:
    def __init__(self, custom_logs=None, custom_stats=None, custom_status=None):
        """
        Инициализация дашборда с возможностью передачи кастомных данных
        
        Args:
            custom_logs: Список логов для отображения в ACTIVITY LOG
            custom_stats: Словарь статистики для отображения
            custom_status: Строка статуса для отображения в шапке
        """
        # Получение реальных данных системы
        self.start_time = datetime.now()
        self.current_process = psutil.Process()  # Текущий процесс Python
        self.peak_ram_mb = 0  # Пиковое использование памяти процессом
        
        # Получение информации о CPU и GPU (один раз при инициализации)
        self.cpu_name = self.get_cpu_name()
        self.gpu_name = self.get_gpu_name()
        
        self.update_system_info()
        
        # Логи активности (можно передать извне)
        self.activity_logs: List[Dict[str, Any]] = custom_logs if custom_logs else [
            {'time': '12:49', 'step': '2 of 4', 'status': 'proving', 'msg': 'Proving task NX-01K977SDKXFTKNGAYA7EESZTV1'},
            {'time': '12:49', 'step': '1 of 4', 'status': 'success', 'msg': 'Got task NX-01K977SDKXFTKNGAYA7EESZTV1'},
            {'time': '12:49', 'step': '', 'status': 'info', 'msg': 'Server adjusted difficulty: requested Medium, assigned Medium (reputation gating)'},
            {'time': '12:47', 'step': '1 of 4', 'status': 'waiting', 'msg': 'Waiting - ready for next task (107) seconds'},
            {'time': '12:47', 'step': '1 of 4', 'status': 'waiting', 'msg': 'Waiting - ready for next task (10) seconds'},
            {'time': '12:45', 'step': '1 of 4', 'status': 'waiting', 'msg': 'Waiting - ready for next task (107) seconds'},
            {'time': '12:45', 'step': '1 of 4', 'status': 'waiting', 'msg': 'Waiting - ready for next task (10) seconds'},
            {'time': '12:45', 'step': '1 of 4', 'status': 'fetching', 'msg': 'Fetching task...'},
            {'time': '12:45', 'step': '', 'status': 'info', 'msg': 'Task completed, ready for next task'},
            {'time': '12:45', 'step': '', 'status': 'completed', 'msg': 'NX-01K977BHRTSBGBG9MAYROR7R8N completed, Task size: 25, Duration: 213s, Difficulty: MEDIUM'},
            {'time': '12:45', 'step': '4 of 4', 'status': 'success', 'msg': 'Proof submitted successfully for task NX-01K977BHRTSBGBG9MAYROR7R8N'},
            {'time': '12:45', 'step': '3 of 4', 'status': 'info', 'msg': 'Submitting proof for task NX-01K977BHRTSBGBG9MAYROR7R8N...'},
            {'time': '12:45', 'step': '3 of 4', 'status': 'success', 'msg': 'Proof generated for task NX-01K977BHRTSBGBG9MAYROR7R8N'},
            {'time': '12:42', 'step': '2 of 4', 'status': 'proving', 'msg': 'Proving task NX-01K977BHRTSBGBG9MAYROR7R8N'},
        ]
        
        # zkVM статистика (можно передать извне)
        self.zkvm_stats = custom_stats if custom_stats else {
            'tasks': 6,
            'completed': '5 / 6',
            'success': '83.3%',
            'runtime': '6m 29s',
            'last': 'Success',
            'last_proof': '11-04 12:45'
        }
        
        self.proving_status = custom_status if custom_status else "Generating proof"
    
    def add_log(self, time_str, status, message, step=''):
        """
        Добавить лог в ACTIVITY LOG (для интеграции с другими модулями)
        
        Args:
            time_str: Время в формате 'HH:MM'
            status: Статус ('success', 'error', 'warning', 'info', 'proving', etc.)
            message: Текст сообщения
            step: Опциональный шаг выполнения ('1 of 4', '2 of 4', etc.)
        """
        log_entry = {
            'time': time_str,
            'step': step,
            'status': status,
            'msg': message
        }
        self.activity_logs.insert(0, log_entry)
        
        # Ограничиваем количество логов (например, последние 100)
        if len(self.activity_logs) > 100:
            self.activity_logs = self.activity_logs[:100]
    
    def update_stats(self, stats_dict):
        """
        Обновить статистику (для интеграции с другими модулями)
        
        Args:
            stats_dict: Словарь со статистикой
        """
        self.zkvm_stats.update(stats_dict)
    
    def update_status(self, status_text):
        """
        Обновить статус в шапке (для интеграции с другими модулями)
        
        Args:
            status_text: Текст статуса
        """
        self.proving_status = status_text
    
    def get_cpu_name(self):
        """Получить название процессора"""
        try:
            if platform.system() == "Windows":
                import subprocess
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'name'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    cpu_name = lines[1].strip()
                    # Сокращаем длинные названия
                    cpu_name = cpu_name.replace('(R)', '').replace('(TM)', '').replace('CPU', '').strip()
                    return cpu_name if len(cpu_name) < 50 else cpu_name[:47] + '...'
            else:
                # Linux/Mac
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if 'model name' in line:
                            cpu_name = line.split(':')[1].strip()
                            cpu_name = cpu_name.replace('(R)', '').replace('(TM)', '').strip()
                            return cpu_name if len(cpu_name) < 50 else cpu_name[:47] + '...'
        except:
            pass
        return platform.processor() or "Unknown CPU"
    
    def get_gpu_name(self):
        """Получить название видеокарты"""
        try:
            if platform.system() == "Windows":
                import subprocess
                result = subprocess.run(
                    ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    gpu_name = lines[1].strip()
                    # Сокращаем длинные названия
                    return gpu_name if len(gpu_name) < 50 else gpu_name[:47] + '...'
            else:
                # Linux - попытка через lspci
                import subprocess
                result = subprocess.run(
                    ['lspci'], 
                    capture_output=True, 
                    text=True,
                    timeout=2
                )
                for line in result.stdout.split('\n'):
                    if 'VGA' in line or 'Display' in line:
                        gpu_name = line.split(':', 1)[1].strip() if ':' in line else line
                        return gpu_name if len(gpu_name) < 50 else gpu_name[:47] + '...'
        except:
            pass
        return "Unknown GPU"
        
    def update_system_info(self):
        """Обновление информации о системе в реальном времени"""
        # Получение имени хоста
        hostname = socket.gethostname()
        
        # Версия Python или системы
        python_version = platform.python_version()
        
        # Uptime (время работы с момента запуска скрипта)
        uptime_seconds = (datetime.now() - self.start_time).total_seconds()
        uptime_str = self.format_uptime(uptime_seconds)
        
        # Количество потоков/ядер
        cpu_threads = psutil.cpu_count(logical=True)
        
        # Общая память
        memory = psutil.virtual_memory()
        total_memory_gb = memory.total / (1024 ** 3)
        
        # Обновление данных системы
        self.system_info = {
            'node': hostname,
            'env': platform.system(),
            'version': python_version,
            'uptime': uptime_str,
            'threads': cpu_threads,
            'memory': f'{total_memory_gb:.1f} GB'
        }
        
        # CPU использование (процент)
        self.cpu_usage = psutil.cpu_percent(interval=0.1)
        
        # CPU использование по ядрам
        self.cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
        
        # RAM использование системы
        self.ram_usage = memory.used / (1024 ** 2)  # MB
        self.ram_total = total_memory_gb
        
        # RAM использование текущим процессом (ETHMashine)
        process_memory = self.current_process.memory_info()
        current_process_ram_mb = process_memory.rss / (1024 ** 2)  # MB
        
        # Обновление пикового значения
        if current_process_ram_mb > self.peak_ram_mb:
            self.peak_ram_mb = current_process_ram_mb
        
        # Получение топ-10 процессов по использованию RAM
        self.top_ram_processes = self.get_top_ram_processes(10)
    
    def get_top_ram_processes(self, limit=10):
        """
        Получить топ процессов по использованию RAM
        
        Args:
            limit: Количество процессов для возврата
            
        Returns:
            List[Dict]: Список словарей с информацией о процессах
        """
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                proc_info = proc.info
                memory_mb = proc_info['memory_info'].rss / (1024 ** 2)
                processes.append({
                    'pid': proc_info['pid'],
                    'name': proc_info['name'],
                    'memory_mb': memory_mb
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        # Сортировка по использованию памяти (по убыванию)
        processes.sort(key=lambda x: x['memory_mb'], reverse=True)
        return processes[:limit]
        
    def format_uptime(self, seconds):
        """Форматирование времени работы"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
        
    def safe_addstr(self, win, y, x, text, attr=0):
        """Безопасная отрисовка текста с проверкой границ"""
        try:
            max_y, max_x = win.getmaxyx()
            if y >= max_y or x >= max_x:
                return
            # Обрезаем текст если он выходит за границы
            available_space = max_x - x - 1
            if available_space > 0:
                text = text[:available_space]
                win.addstr(y, x, text, attr)
        except curses.error:
            pass
    
    def draw_box(self, win, y, x, height, width, title):
        """Рисует рамку с заголовком"""
        if height < 2 or width < 2:
            return
            
        color = curses.color_pair(1)
        
        # Верхняя граница с заголовком
        top_line = '┌' + title + '─' * max(0, width - len(title) - 2) + '┐'
        self.safe_addstr(win, y, x, top_line[:width], color)
        
        # Боковые границы
        for i in range(1, height - 1):
            self.safe_addstr(win, y + i, x, '│', color)
            self.safe_addstr(win, y + i, x + width - 1, '│', color)
        
        # Нижняя граница
        bottom_line = '└' + '─' * max(0, width - 2) + '┘'
        self.safe_addstr(win, y + height - 1, x, bottom_line[:width], color)
    
    def draw_progress_bar(self, win, y, x, width, value, max_value, color_pair):
        """Рисует прогресс-бар"""
        if width <= 0:
            return
        filled = int((value / max_value) * width) if max_value > 0 else 0
        filled = min(filled, width)
        bar = '█' * filled
        self.safe_addstr(win, y, x, bar, curses.color_pair(color_pair))
    
    def draw(self, stdscr):
        """Основная функция отрисовки"""
        curses.curs_set(0)
        stdscr.nodelay(1)
        stdscr.timeout(100)
        
        # Инициализация цветов
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_GREEN)
        
        while True:
            # Обновление системной информации
            self.update_system_info()
            
            # Полная очистка экрана
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            
            # Проверка минимального размера
            if height < 25 or width < 80:
                msg = "Terminal too small! Minimum 80x25"
                self.safe_addstr(stdscr, height//2, max(0, width//2 - len(msg)//2), msg, curses.color_pair(4))
                stdscr.refresh()
                key = stdscr.getch()
                if key == ord('q') or key == ord('Q'):
                    break
                continue
            
            # Заголовок
            title = f"ETHMashine v{self.system_info['version']}"
            self.safe_addstr(stdscr, 0, width//2 - len(title)//2, title, curses.color_pair(5) | curses.A_BOLD)
            
            # Пустая строка
            self.safe_addstr(stdscr, 1, 0, ' ' * width)
            
            # Статус бар
            status_text = f" PROVING - {self.proving_status} "
            status_line = status_text + ' ' * max(0, width - len(status_text))
            self.safe_addstr(stdscr, 2, 0, status_line[:width], curses.color_pair(6))
            
            # Пустая строка
            self.safe_addstr(stdscr, 3, 0, ' ' * width)
            
            # Расчет размеров панелей
            panel_height = (height - 6) // 2
            # SYSTEM INFO займет 18% ширины (уменьшено на 40% от 30%), ACTIVITY LOG - ~82%
            left_width = int(width * 0.18)  # 18% для SYSTEM INFO
            right_width = width - left_width - 1  # ~82% для ACTIVITY LOG
            
            if panel_height < 5:
                panel_height = 5
            
            # SYSTEM INFO
            self.draw_box(stdscr, 4, 0, panel_height, left_width, "SYSTEM INFO")
            y_offset = 5
            
            # Hostname
            if y_offset < 4 + panel_height - 1:
                self.safe_addstr(stdscr, y_offset, 2, "Node:", curses.color_pair(2))
                node_text = self.system_info['node'][:left_width-8]
                self.safe_addstr(stdscr, y_offset, 8, node_text)
            
            # OS
            if y_offset + 1 < 4 + panel_height - 1:
                self.safe_addstr(stdscr, y_offset + 1, 2, "OS:", curses.color_pair(2))
                os_info = f"{self.system_info['env']} {platform.release()}"
                self.safe_addstr(stdscr, y_offset + 1, 6, os_info[:left_width-8])
            
            # Python version
            if y_offset + 2 < 4 + panel_height - 1:
                self.safe_addstr(stdscr, y_offset + 2, 2, "Py:", curses.color_pair(2))
                self.safe_addstr(stdscr, y_offset + 2, 6, self.system_info['version'][:left_width-8])
            
            # Uptime
            if y_offset + 3 < 4 + panel_height - 1:
                self.safe_addstr(stdscr, y_offset + 3, 2, "Up:", curses.color_pair(2))
                self.safe_addstr(stdscr, y_offset + 3, 6, self.system_info['uptime'][:left_width-8])
            
            # CPU name (новое)
            if y_offset + 4 < 4 + panel_height - 1:
                self.safe_addstr(stdscr, y_offset + 4, 2, "CPU:", curses.color_pair(3))
                cpu_name_short = self.cpu_name[:left_width-7]
                self.safe_addstr(stdscr, y_offset + 4, 7, cpu_name_short)
            
            # GPU name (новое)
            if y_offset + 5 < 4 + panel_height - 1:
                self.safe_addstr(stdscr, y_offset + 5, 2, "GPU:", curses.color_pair(3))
                gpu_name_short = self.gpu_name[:left_width-7]
                self.safe_addstr(stdscr, y_offset + 5, 7, gpu_name_short)
            
            # RAM
            if y_offset + 6 < 4 + panel_height - 1:
                self.safe_addstr(stdscr, y_offset + 6, 2, "RAM:", curses.color_pair(2))
                ram_info = f"{self.ram_usage:.0f}MB/{self.system_info['memory']}"
                self.safe_addstr(stdscr, y_offset + 6, 7, ram_info[:left_width-9])
            
            # Disk
            if y_offset + 7 < 4 + panel_height - 1:
                disk = psutil.disk_usage('/')
                self.safe_addstr(stdscr, y_offset + 7, 2, "Disk:", curses.color_pair(2))
                disk_info = f"{disk.used / (1024**3):.0f}GB/{disk.total / (1024**3):.0f}GB"
                self.safe_addstr(stdscr, y_offset + 7, 8, disk_info[:left_width-10])
            
            # ACTIVITY LOG
            self.draw_box(stdscr, 4, left_width + 1, panel_height, right_width, "ACTIVITY LOG")
            log_y = 5
            max_logs = panel_height - 3
            
            for i, log in enumerate(self.activity_logs[:max_logs]):
                if log_y >= 4 + panel_height - 2:
                    break
                
                # Иконка статуса
                icon = ' '
                icon_color = 1
                if log['status'] == 'success':
                    icon = '✓'
                    icon_color = 2
                elif log['status'] == 'proving':
                    icon = '⟳'
                    icon_color = 3
                
                self.safe_addstr(stdscr, log_y, left_width + 3, icon, curses.color_pair(icon_color))
                
                # Формирование текста лога
                step_text = f"{log['step']}: " if log['step'] else ""
                log_text = f"{log['time']} {step_text}{log['msg']}"
                
                # Обрезка если слишком длинный
                max_log_width = right_width - 7
                if len(log_text) > max_log_width:
                    log_text = log_text[:max_log_width - 3] + '...'
                
                color = curses.color_pair(2 if log['status'] == 'success' else 1)
                self.safe_addstr(stdscr, log_y, left_width + 5, log_text, color)
                log_y += 1
            
            # Нижние панели
            bottom_y = 4 + panel_height + 1
            bottom_height = height - bottom_y - 2
            
            if bottom_height < 3:
                bottom_height = 3
            
            # Увеличиваем ширину CPU Usage для размещения информации по ядрам
            bottom_left_width = int(width * 0.4)  # 40% для CPU
            bottom_mid_width = int(width * 0.35)   # 35% для RAM
            bottom_right_width = width - bottom_left_width - bottom_mid_width - 2
            
            # CPU Usage
            self.draw_box(stdscr, bottom_y, 0, bottom_height, bottom_left_width, "CPU Usage")
            cpu_y = bottom_y + 1
            
            # Общая нагрузка на процессор (жирным шрифтом с явным указанием)
            if cpu_y < bottom_y + bottom_height - 1:
                cpu_label = "═══ TOTAL CPU ═══"
                label_x = 2 + (bottom_left_width - 4 - len(cpu_label)) // 2
                self.safe_addstr(stdscr, cpu_y, label_x, cpu_label, curses.color_pair(5) | curses.A_BOLD)
            
            if cpu_y + 1 < bottom_y + bottom_height - 1:
                cpu_text = f"{self.cpu_usage:.1f}%"
                text_x = 2 + (bottom_left_width - 4 - len(cpu_text)) // 2
                cpu_display_color = 2 if self.cpu_usage < 70 else (3 if self.cpu_usage < 90 else 4)
                self.safe_addstr(stdscr, cpu_y + 1, text_x, cpu_text, curses.color_pair(cpu_display_color) | curses.A_BOLD)
            
            # Прогресс-бар общего CPU на всю ширину
            if cpu_y + 2 < bottom_y + bottom_height - 1:
                bar_width = bottom_left_width - 4
                if bar_width > 0:
                    cpu_color = 2 if self.cpu_usage < 70 else (3 if self.cpu_usage < 90 else 4)
                    self.draw_progress_bar(stdscr, cpu_y + 2, 2, bar_width, self.cpu_usage, 100, cpu_color)
            
            # Разделитель
            if cpu_y + 3 < bottom_y + bottom_height - 1:
                separator = "─" * (bottom_left_width - 4)
                self.safe_addstr(stdscr, cpu_y + 3, 2, separator, curses.color_pair(1))
            
            # Нагрузка по ядрам (компактно)
            cores_start_y = cpu_y + 4
            if cores_start_y < bottom_y + bottom_height - 1:
                # Заголовок для ядер
                core_label = "Per Core:"
                self.safe_addstr(stdscr, cores_start_y, 2, core_label, curses.color_pair(5) | curses.A_BOLD)
                
                # Отображение ядер построчно (по 2-4 ядра в строку в зависимости от ширины)
                available_width = bottom_left_width - 4
                cores_per_row = max(2, min(4, available_width // 15))  # Динамическое количество
                core_y = cores_start_y + 1
                core_width = available_width // cores_per_row
                
                for i, core_usage in enumerate(self.cpu_per_core):
                    if core_y >= bottom_y + bottom_height - 1:
                        break
                    
                    col = i % cores_per_row
                    if col == 0 and i > 0:
                        core_y += 1
                        if core_y >= bottom_y + bottom_height - 1:
                            break
                    
                    x_offset = 2 + col * core_width
                    core_text = f"C{i:2d}:{core_usage:5.1f}%"
                    core_color = 2 if core_usage < 70 else (3 if core_usage < 90 else 4)
                    self.safe_addstr(stdscr, core_y, x_offset, core_text, curses.color_pair(core_color))
            
            # RAM Usage
            self.draw_box(stdscr, bottom_y, bottom_left_width + 1, bottom_height, bottom_mid_width, "RAM Usage")
            ram_y = bottom_y + 1
            
            # Общее использование RAM
            ram_percent = (self.ram_usage / (self.ram_total * 1024)) * 100
            ram_header = "═══ SYSTEM RAM ═══"
            header_x = bottom_left_width + 3 + (bottom_mid_width - 6 - len(ram_header)) // 2
            if ram_y < bottom_y + bottom_height - 1:
                self.safe_addstr(stdscr, ram_y, header_x, ram_header, curses.color_pair(5) | curses.A_BOLD)
            
            ram_text = f"{self.ram_usage:.0f}MB / {self.ram_total:.1f}GB ({ram_percent:.1f}%)"
            if ram_y + 1 < bottom_y + bottom_height - 1:
                self.safe_addstr(stdscr, ram_y + 1, bottom_left_width + 3, ram_text, curses.color_pair(2))
            
            # Прогресс-бар RAM на всю ширину
            if ram_y + 2 < bottom_y + bottom_height - 1:
                bar_width = bottom_mid_width - 4
                if bar_width > 0:
                    ram_color = 2 if ram_percent < 70 else (3 if ram_percent < 90 else 4)
                    self.draw_progress_bar(stdscr, ram_y + 2, bottom_left_width + 3, bar_width, ram_percent, 100, ram_color)
            
            # Разделитель
            if ram_y + 3 < bottom_y + bottom_height - 1:
                separator = "─" * (bottom_mid_width - 4)
                self.safe_addstr(stdscr, ram_y + 3, bottom_left_width + 3, separator, curses.color_pair(1))
            
            # Top 10 процессов по RAM
            top_start_y = ram_y + 4
            if top_start_y < bottom_y + bottom_height - 1:
                top_label = "Top 10 Processes:"
                self.safe_addstr(stdscr, top_start_y, bottom_left_width + 3, top_label, curses.color_pair(5) | curses.A_BOLD)
                
                proc_y = top_start_y + 1
                for i, proc in enumerate(self.top_ram_processes[:10]):
                    if proc_y >= bottom_y + bottom_height - 1:
                        break
                    
                    # Форматирование имени процесса (обрезка если длинное)
                    max_name_len = bottom_mid_width - 20
                    proc_name = proc['name'][:max_name_len] if len(proc['name']) > max_name_len else proc['name']
                    
                    # Форматирование строки
                    proc_text = f"{i+1:2d}. {proc_name:<{max_name_len}} {proc['memory_mb']:>6.1f}MB"
                    
                    # Цвет в зависимости от использования
                    proc_color = 2 if proc['memory_mb'] < 500 else (3 if proc['memory_mb'] < 1000 else 4)
                    self.safe_addstr(stdscr, proc_y, bottom_left_width + 3, proc_text, curses.color_pair(proc_color))
                    proc_y += 1
            
            # Peak RAM (процесс ETHMashine)
            peak_x = bottom_left_width + bottom_mid_width + 2
            peak_half_height = bottom_height // 2
            self.draw_box(stdscr, bottom_y, peak_x, peak_half_height, bottom_right_width, "Peak RAM (ETHMashine)")
            
            peak_text = f"{self.peak_ram_mb:.1f} MB"
            if bottom_y + 1 < bottom_y + peak_half_height - 1:
                self.safe_addstr(stdscr, bottom_y + 1, peak_x + 2, peak_text, curses.color_pair(1))
            
            # Прогресс-бар Peak RAM на всю ширину
            if bottom_y + 2 < bottom_y + peak_half_height - 1:
                bar_width = bottom_right_width - 4
                if bar_width > 0:
                    # Масштабируем для отображения (максимум 1GB для прогресс-бара)
                    max_ram_for_bar = 1024  # MB
                    peak_color = 2 if self.peak_ram_mb < 700 else (3 if self.peak_ram_mb < 900 else 4)
                    self.draw_progress_bar(stdscr, bottom_y + 2, peak_x + 2, bar_width, 
                                          min(self.peak_ram_mb, max_ram_for_bar), max_ram_for_bar, peak_color)
            
            # zkVM STATS
            stats_y = bottom_y + peak_half_height + 1
            stats_height = bottom_height - peak_half_height - 1
            if stats_height > 2:
                self.draw_box(stdscr, stats_y, peak_x, stats_height, bottom_right_width, "ETHMashine STATS")
                
                stats_content_y = stats_y + 1
                stats_x = peak_x + 2
                
                if stats_content_y < stats_y + stats_height - 1:
                    self.safe_addstr(stdscr, stats_content_y, stats_x, "Tasks: ", curses.color_pair(2))
                    self.safe_addstr(stdscr, stats_content_y, stats_x + 7, str(self.zkvm_stats['tasks']))
                
                if stats_content_y + 1 < stats_y + stats_height - 1:
                    self.safe_addstr(stdscr, stats_content_y + 1, stats_x, "Completed: ", curses.color_pair(2))
                    self.safe_addstr(stdscr, stats_content_y + 1, stats_x + 11, self.zkvm_stats['completed'])
                
                if stats_content_y + 2 < stats_y + stats_height - 1:
                    self.safe_addstr(stdscr, stats_content_y + 2, stats_x, "Success: ", curses.color_pair(2))
                    self.safe_addstr(stdscr, stats_content_y + 2, stats_x + 9, self.zkvm_stats['success'])
                
                if stats_content_y + 3 < stats_y + stats_height - 1:
                    self.safe_addstr(stdscr, stats_content_y + 3, stats_x, "Runtime: ", curses.color_pair(2))
                    self.safe_addstr(stdscr, stats_content_y + 3, stats_x + 9, self.zkvm_stats['runtime'])
                
                if stats_content_y + 4 < stats_y + stats_height - 1:
                    self.safe_addstr(stdscr, stats_content_y + 4, stats_x, "Last: ", curses.color_pair(2))
                    self.safe_addstr(stdscr, stats_content_y + 4, stats_x + 6, self.zkvm_stats['last'], curses.color_pair(2))
            
            # Футер
            if height > 1:
                footer = "[Q] Quit | ETHMashine Dashboard"
                footer_y = height - 1
                self.safe_addstr(stdscr, footer_y, width // 2 - len(footer) // 2, footer, curses.color_pair(1))
            
            stdscr.refresh()
            
            # Обработка ввода
            key = stdscr.getch()
            if key == ord('q') or key == ord('Q'):
                break
            
            time.sleep(0.1)

def main():
    dashboard = ETHMashineDashboard()
    try:
        curses.wrapper(dashboard.draw)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()