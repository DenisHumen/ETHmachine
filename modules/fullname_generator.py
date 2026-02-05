#!/usr/bin/env python3
"""
Модуль генерации имён и фамилий
Поддерживает генерацию для разных языков: RU, UA, ENG
"""

import os
import random
import platform
from pathlib import Path
from datetime import datetime
from colorama import Fore, init
from loguru import logger

init(autoreset=True)

# Базы имён и фамилий для разных языков
NAMES_DATABASE = {
    'ru': {
        'male_first': [
            'Александр', 'Дмитрий', 'Максим', 'Сергей', 'Андрей', 'Алексей', 'Артём', 'Илья', 'Кирилл', 'Михаил',
            'Иван', 'Егор', 'Роман', 'Владимир', 'Павел', 'Никита', 'Денис', 'Евгений', 'Даниил', 'Тимофей',
            'Владислав', 'Игорь', 'Антон', 'Константин', 'Олег', 'Николай', 'Юрий', 'Виктор', 'Станислав', 'Глеб',
            'Артур', 'Матвей', 'Марк', 'Лев', 'Степан', 'Федор', 'Ярослав', 'Григорий', 'Богдан', 'Савелий',
            'Тимур', 'Вадим', 'Семен', 'Руслан', 'Борис', 'Валентин', 'Леонид', 'Анатолий', 'Василий', 'Петр'
        ],
        'female_first': [
            'Анастасия', 'Мария', 'Дарья', 'Анна', 'Екатерина', 'Полина', 'Виктория', 'Елизавета', 'Александра', 'София',
            'Наталья', 'Ольга', 'Татьяна', 'Ирина', 'Юлия', 'Светлана', 'Елена', 'Валерия', 'Алина', 'Ксения',
            'Вероника', 'Марина', 'Кристина', 'Диана', 'Арина', 'Милана', 'Камила', 'Ева', 'Варвара', 'Алиса',
            'Ульяна', 'Кира', 'Маргарита', 'Яна', 'Василиса', 'Таисия', 'Стефания', 'Майя', 'Злата', 'Вера',
            'Надежда', 'Любовь', 'Людмила', 'Валентина', 'Инна', 'Оксана', 'Лариса', 'Нина', 'Галина', 'Зоя'
        ],
        'last': [
            'Иванов', 'Смирнов', 'Кузнецов', 'Попов', 'Васильев', 'Петров', 'Соколов', 'Михайлов', 'Новиков', 'Федоров',
            'Морозов', 'Волков', 'Алексеев', 'Лебедев', 'Семенов', 'Егоров', 'Павлов', 'Козлов', 'Степанов', 'Николаев',
            'Орлов', 'Андреев', 'Макаров', 'Никитин', 'Захаров', 'Зайцев', 'Соловьев', 'Борисов', 'Яковлев', 'Григорьев',
            'Романов', 'Воробьев', 'Сергеев', 'Кузьмин', 'Максимов', 'Леонов', 'Голубев', 'Виноградов', 'Богданов', 'Воронов',
            'Белов', 'Медведев', 'Антонов', 'Тарасов', 'Жуков', 'Баранов', 'Филиппов', 'Комаров', 'Давыдов', 'Беляев',
            'Герасимов', 'Богомолов', 'Дмитриев', 'Сидоров', 'Матвеев', 'Титов', 'Марков', 'Миронов', 'Крылов', 'Куликов',
            'Карпов', 'Власов', 'Мельников', 'Денисов', 'Гаврилов', 'Тихонов', 'Казаков', 'Афанасьев', 'Данилов', 'Савельев',
            'Тимофеев', 'Фомин', 'Чернов', 'Абрамов', 'Мартынов', 'Ефимов', 'Федотов', 'Щербаков', 'Назаров', 'Калинин'
        ]
    },
    'ua': {
        'male_first': [
            'Олександр', 'Дмитро', 'Максим', 'Сергій', 'Андрій', 'Олексій', 'Артем', 'Ілля', 'Кирило', 'Михайло',
            'Іван', 'Єгор', 'Роман', 'Володимир', 'Павло', 'Нікіта', 'Денис', 'Євген', 'Данило', 'Тимофій',
            'Владислав', 'Ігор', 'Антон', 'Костянтин', 'Олег', 'Микола', 'Юрій', 'Віктор', 'Станіслав', 'Гліб',
            'Артур', 'Матвій', 'Марк', 'Лев', 'Степан', 'Федір', 'Ярослав', 'Григорій', 'Богдан', 'Савелій',
            'Тимур', 'Вадим', 'Семен', 'Руслан', 'Борис', 'Валентин', 'Леонід', 'Анатолій', 'Василь', 'Петро'
        ],
        'female_first': [
            'Анастасія', 'Марія', 'Дар\'я', 'Анна', 'Катерина', 'Поліна', 'Вікторія', 'Єлизавета', 'Олександра', 'Софія',
            'Наталія', 'Ольга', 'Тетяна', 'Ірина', 'Юлія', 'Світлана', 'Олена', 'Валерія', 'Аліна', 'Ксенія',
            'Вероніка', 'Марина', 'Христина', 'Діана', 'Аріна', 'Мілана', 'Каміла', 'Єва', 'Варвара', 'Аліса',
            'Уляна', 'Кіра', 'Маргарита', 'Яна', 'Василиса', 'Таїсія', 'Стефанія', 'Майя', 'Злата', 'Віра',
            'Надія', 'Любов', 'Людмила', 'Валентина', 'Інна', 'Оксана', 'Лариса', 'Ніна', 'Галина', 'Зоя'
        ],
        'last': [
            'Іваненко', 'Коваленко', 'Бондаренко', 'Ткаченко', 'Кравченко', 'Ковальчук', 'Шевченко', 'Поліщук', 'Мельник', 'Петренко',
            'Марченко', 'Клименко', 'Павленко', 'Савченко', 'Литвиненко', 'Романенко', 'Семенченко', 'Сидоренко', 'Руденко', 'Білоус',
            'Коваль', 'Іващенко', 'Гончаренко', 'Власенко', 'Ковальов', 'Дмитренко', 'Левченко', 'Олійник', 'Захарченко', 'Макаренко',
            'Лисенко', 'Гриценко', 'Данильченко', 'Тимошенко', 'Нечипоренко', 'Павлюк', 'Михайленко', 'Костенко', 'Василенко', 'Волошин',
            'Ковбасюк', 'Степаненко', 'Кириленко', 'Федоренко', 'Тарасенко', 'Яременко', 'Сергієнко', 'Максименко', 'Григоренко', 'Андрієнко',
            'Матвієнко', 'Панченко', 'Тесленко', 'Приходько', 'Гаврилюк', 'Бойко', 'Гордієнко', 'Демченко', 'Левицький', 'Романюк',
            'Колесник', 'Юрченко', 'Зінченко', 'Богданов', 'Єрмоленко', 'Лукащук', 'Панасюк', 'Данилюк', 'Мороз', 'Гайдук'
        ]
    },
    'eng': {
        'male_first': [
            'James', 'John', 'Robert', 'Michael', 'William', 'David', 'Richard', 'Joseph', 'Thomas', 'Charles',
            'Christopher', 'Daniel', 'Matthew', 'Anthony', 'Mark', 'Donald', 'Steven', 'Paul', 'Andrew', 'Joshua',
            'Kenneth', 'Kevin', 'Brian', 'George', 'Edward', 'Ronald', 'Timothy', 'Jason', 'Jeffrey', 'Ryan',
            'Jacob', 'Gary', 'Nicholas', 'Eric', 'Jonathan', 'Stephen', 'Larry', 'Justin', 'Scott', 'Brandon',
            'Benjamin', 'Samuel', 'Raymond', 'Gregory', 'Alexander', 'Patrick', 'Frank', 'Dennis', 'Jerry', 'Tyler'
        ],
        'female_first': [
            'Mary', 'Patricia', 'Jennifer', 'Linda', 'Elizabeth', 'Barbara', 'Susan', 'Jessica', 'Sarah', 'Karen',
            'Nancy', 'Lisa', 'Betty', 'Margaret', 'Sandra', 'Ashley', 'Dorothy', 'Kimberly', 'Emily', 'Donna',
            'Michelle', 'Carol', 'Amanda', 'Melissa', 'Deborah', 'Stephanie', 'Rebecca', 'Laura', 'Sharon', 'Cynthia',
            'Kathleen', 'Amy', 'Shirley', 'Angela', 'Helen', 'Anna', 'Brenda', 'Pamela', 'Nicole', 'Samantha',
            'Katherine', 'Emma', 'Ruth', 'Christine', 'Catherine', 'Debra', 'Rachel', 'Carolyn', 'Janet', 'Virginia'
        ],
        'last': [
            'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez',
            'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson', 'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin',
            'Lee', 'Perez', 'Thompson', 'White', 'Harris', 'Sanchez', 'Clark', 'Ramirez', 'Lewis', 'Robinson',
            'Walker', 'Young', 'Allen', 'King', 'Wright', 'Scott', 'Torres', 'Nguyen', 'Hill', 'Flores',
            'Green', 'Adams', 'Nelson', 'Baker', 'Hall', 'Rivera', 'Campbell', 'Mitchell', 'Carter', 'Roberts',
            'Gomez', 'Phillips', 'Evans', 'Turner', 'Diaz', 'Parker', 'Cruz', 'Edwards', 'Collins', 'Reyes',
            'Stewart', 'Morris', 'Morales', 'Murphy', 'Cook', 'Rogers', 'Gutierrez', 'Ortiz', 'Morgan', 'Cooper',
            'Peterson', 'Bailey', 'Reed', 'Kelly', 'Howard', 'Ramos', 'Kim', 'Cox', 'Ward', 'Richardson'
        ]
    }
}


def get_csv_delimiter():
    """
    Определяет разделитель CSV в зависимости от ОС
    
    Returns:
        str: ',' для Linux/macOS, ';' для Windows
    """
    system = platform.system().lower()
    if system == 'windows':
        return ';'
    else:  # linux, darwin (macOS)
        return ','


def generate_unique_fullnames(language: str, quantity: int, gender_mix: bool = True) -> list:
    """
    Генерирует уникальные комбинации имён и фамилий
    
    Args:
        language: Язык генерации ('ru', 'ua', 'eng')
        quantity: Количество генерируемых имён
        gender_mix: Генерировать смешанные полы (True) или только мужские (False)
    
    Returns:
        list: Список уникальных полных имён
    """
    if language not in NAMES_DATABASE:
        raise ValueError(f"Неподдерживаемый язык: {language}. Доступные: {list(NAMES_DATABASE.keys())}")
    
    db = NAMES_DATABASE[language]
    generated_names = set()
    attempts = 0
    max_attempts = quantity * 100  # Защита от бесконечного цикла
    
    # Рассчитываем максимально возможное количество уникальных комбинаций
    if gender_mix:
        max_combinations = (len(db['male_first']) + len(db['female_first'])) * len(db['last'])
    else:
        max_combinations = len(db['male_first']) * len(db['last'])
    
    if quantity > max_combinations:
        logger.warning(
            f"Запрошено {quantity} имён, но максимум возможно {max_combinations} уникальных комбинаций. "
            f"Будет сгенерировано {max_combinations} имён."
        )
        quantity = max_combinations
    
    logger.info(f"Начинаем генерацию {quantity} уникальных имён на языке: {language}")
    
    while len(generated_names) < quantity and attempts < max_attempts:
        attempts += 1
        
        # Выбираем пол
        if gender_mix:
            is_male = random.choice([True, False])
        else:
            is_male = True
        
        # Выбираем имя и фамилию
        if is_male:
            first_name = random.choice(db['male_first'])
        else:
            first_name = random.choice(db['female_first'])
        
        last_name = random.choice(db['last'])
        
        # Для русского и украинского языков учитываем склонение фамилий
        if language in ['ru', 'ua'] and not is_male:
            if last_name.endswith('ов') or last_name.endswith('ів'):
                last_name = last_name + 'а'
            elif last_name.endswith('ин') or last_name.endswith('ін'):
                last_name = last_name + 'а'
            elif last_name.endswith('ий') or last_name.endswith('ій'):
                last_name = last_name[:-2] + 'ая'
            elif language == 'ua' and (last_name.endswith('енко') or last_name.endswith('ко')):
                pass  # Украинские фамилии на -енко не склоняются
        
        full_name = f"{first_name} {last_name}"
        generated_names.add(full_name)
        
        # Прогресс каждые 1000 имён
        if len(generated_names) % 1000 == 0:
            logger.debug(f"Сгенерировано {len(generated_names)}/{quantity} имён")
    
    if len(generated_names) < quantity:
        logger.warning(
            f"Удалось сгенерировать только {len(generated_names)} из {quantity} запрошенных имён "
            f"после {attempts} попыток"
        )
    
    # Преобразуем в список и перемешиваем для лучшего распределения
    result = list(generated_names)
    random.shuffle(result)
    
    return result


def save_to_csv(names: list, language: str, output_dir: str = 'result'):
    """
    Сохраняет имена в CSV файл
    
    Args:
        names: Список имён
        language: Язык для имени файла
        output_dir: Директория для сохранения
    
    Returns:
        str: Путь к сохранённому файлу
    """
    # Создаём директорию если не существует
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Генерируем имя файла с временной меткой
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"fullnames_{language}_{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)
    
    # Определяем разделитель
    delimiter = get_csv_delimiter()
    
    # Сохраняем в файл
    try:
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            # Заголовок
            f.write(f"fullname{delimiter}language\n")
            
            # Данные
            for name in names:
                f.write(f"{name}{delimiter}{language}\n")
        
        logger.success(f"Сохранено {len(names)} имён в файл: {filepath}")
        return filepath
    
    except Exception as e:
        logger.error(f"Ошибка при сохранении файла: {e}")
        raise


def generate_fullnames_menu():
    """
    Главная функция с интерактивным меню для генерации имён
    """
    from questionary import select, Choice
    
    try:
        # Импортируем настройки
        from config.modules.cfg_generators import FULLNAME_GENERATOR
        quantity = FULLNAME_GENERATOR.get('QUANTITY', 100)
    except ImportError:
        logger.warning("Не удалось импортировать настройки из config.py, используются значения по умолчанию")
        quantity = 100
    
    print(Fore.CYAN + "\n" + "="*70)
    print(Fore.CYAN + "👤 ГЕНЕРАТОР ПОЛНЫХ ИМЁН (ИМЯ + ФАМИЛИЯ)")
    print(Fore.CYAN + "="*70)
    
    # Выбор языка
    language_choice = select(
        "Выберите язык генерации:",
        choices=[
            Choice('🇷🇺 Русский (Russian)', 'ru'),
            Choice('🇺🇦 Українська (Ukrainian)', 'ua'),
            Choice('🇬🇧 English', 'eng'),
            Choice('🔙 Назад (Back)', 'back')
        ],
        qmark='🌍',
        pointer='👉'
    ).ask()
    
    if language_choice == 'back':
        return
    
    # Информация о количестве
    print(Fore.YELLOW + f"\nКоличество имён для генерации: {quantity}")
    print(Fore.YELLOW + f"Параметр настраивается в config/config.py -> FULLNAME_GENERATOR['QUANTITY']")
    
    # Определяем ОС и разделитель
    os_type = platform.system()
    delimiter = get_csv_delimiter()
    print(Fore.CYAN + f"\nОперационная система: {os_type}")
    print(Fore.CYAN + f"Разделитель CSV: '{delimiter}' {'(точка с запятой)' if delimiter == ';' else '(запятая)'}")
    
    # Генерация
    print(Fore.GREEN + f"\n⏳ Генерация {quantity} уникальных имён...")
    
    try:
        names = generate_unique_fullnames(language_choice, quantity, gender_mix=True)
        
        print(Fore.GREEN + f"✅ Успешно сгенерировано {len(names)} уникальных имён")
        
        # Показываем примеры
        print(Fore.CYAN + "\n📋 Примеры сгенерированных имён:")
        for i, name in enumerate(names[:10], 1):
            print(Fore.WHITE + f"  {i}. {name}")
        
        if len(names) > 10:
            print(Fore.WHITE + f"  ... и ещё {len(names) - 10} имён")
        
        # Сохранение
        filepath = save_to_csv(names, language_choice)
        
        print(Fore.GREEN + f"\n✅ Файл сохранён: {filepath}")
        print(Fore.CYAN + f"📊 Формат: fullname{delimiter}language")
        print(Fore.CYAN + "="*70 + "\n")
        
        input(Fore.YELLOW + "Нажмите Enter для продолжения...")
        
    except Exception as e:
        logger.error(f"Ошибка при генерации имён: {e}")
        print(Fore.RED + f"\n❌ Ошибка: {e}")
        input(Fore.YELLOW + "\nНажмите Enter для продолжения...")


if __name__ == "__main__":
    # Настройка логирования
    logger.add(
        "log/fullname_generator.log",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        level="DEBUG"
    )
    
    # Запуск меню
    generate_fullnames_menu()
