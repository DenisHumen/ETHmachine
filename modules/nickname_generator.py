"""
Генератор человечески выглядящих никнеймов
"""
import random
import os
from config.config import NICKNAME_GENERATOR
from loguru import logger


def log_info(message: str):
    """Информационное сообщение - синий цвет"""
    logger.opt(colors=True).info(f"<blue>{message}</blue>")

def log_success(message: str):
    """Успешное выполнение - зеленый цвет"""
    logger.opt(colors=True).info(f"<green>{message}</green>")

def log_error(message: str):
    """Ошибка - красный цвет"""
    logger.opt(colors=True).error(f"<red>{message}</red>")


class NicknameGenerator:
    def __init__(self):
        # Слоги для создания реалистичных имен
        self.consonants = ['b', 'c', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'm', 
                          'n', 'p', 'q', 'r', 's', 't', 'v', 'w', 'x', 'y', 'z']
        self.vowels = ['a', 'e', 'i', 'o', 'u']
        
        # Популярные префиксы и суффиксы для никнеймов
        self.prefixes = ['dark', 'cool', 'super', 'mega', 'ultra', 'pro', 'neo', 
                        'cyber', 'shadow', 'frost', 'fire', 'storm', 'night', 
                        'star', 'sky', 'moon', 'sun', 'wild', 'free', 'red',
                        'blue', 'gold', 'silver', 'ice', 'hot', 'fast', 'ninja']
        
        self.suffixes = ['er', 'or', 'man', 'boy', 'girl', 'kid', 'pro', 'master',
                        'lord', 'king', 'queen', 'star', 'wolf', 'fox', 'cat',
                        'tiger', 'dragon', 'eagle', 'hawk', 'lion', 'bear',
                        'hunter', 'warrior', 'knight', 'ace', 'legend']
        
        # Специальные символы
        self.special_chars = ['_', '-', '.']
        
        # Популярные слова для никнеймов
        self.words = ['gamer', 'player', 'user', 'admin', 'noob', 'newbie',
                     'veteran', 'expert', 'rookie', 'champion', 'winner', 
                     'loser', 'fighter', 'warrior', 'guardian', 'defender',
                     'attacker', 'sniper', 'scout', 'medic', 'tank', 'support']
    
    def _generate_syllable_name(self, length):
        """Генерирует имя из слогов (согласная + гласная)"""
        name = ''
        target_length = random.randint(max(3, length - 2), length)
        
        while len(name) < target_length:
            if len(name) == 0 or name[-1] in self.vowels:
                # Добавляем согласную
                name += random.choice(self.consonants)
            else:
                # Добавляем гласную
                name += random.choice(self.vowels)
                
            if len(name) >= target_length:
                break
        
        # Убеждаемся что имя не заканчивается на гласную (более натурально)
        if len(name) > 1 and name[-1] in self.vowels and random.choice([True, False]):
            consonants_ending = ['x', 'z', 'r', 's', 't', 'n', 'm']
            name += random.choice(consonants_ending)
        
        return name
    
    def _generate_word_combination(self, target_length):
        """Генерирует никнейм из комбинации слов"""
        min_len = NICKNAME_GENERATOR['MIN_LENGTH']
        max_len = NICKNAME_GENERATOR['MAX_LENGTH']
        
        # Выбираем стратегию генерации
        strategy = random.choice(['prefix_suffix', 'word_number', 'word_word', 'syllable_word'])
        
        if strategy == 'prefix_suffix':
            prefix = random.choice(self.prefixes)
            suffix = random.choice(self.suffixes)
            base_name = prefix + suffix
            
        elif strategy == 'word_number':
            word = random.choice(self.words + self.prefixes)
            number = random.randint(1, 9999)
            base_name = f"{word}{number}"
            
        elif strategy == 'word_word':
            word1 = random.choice(self.prefixes)
            word2 = random.choice(self.suffixes)
            base_name = word1 + word2
            
        else:  # syllable_word
            syllable_part = self._generate_syllable_name(random.randint(4, 7))
            word_part = random.choice(self.suffixes)
            base_name = syllable_part + word_part
        
        # Подгоняем под нужную длину
        if len(base_name) > target_length:
            base_name = base_name[:target_length]
        elif len(base_name) < min_len:
            # Добавляем цифры для увеличения длины
            while len(base_name) < min_len and len(base_name) < target_length:
                base_name += str(random.randint(0, 9))
        
        return base_name
    
    def _add_special_chars(self, name):
        """Добавляет специальные символы в никнейм"""
        if not NICKNAME_GENERATOR.get('USE_SPECIAL_CHARS', True):
            return name
            
        # 30% шанс добавить специальные символы
        if random.random() > 0.3:
            return name
            
        # Выбираем позицию для вставки специального символа
        special_char = random.choice(self.special_chars)
        
        # Избегаем добавления в начало и конец
        if len(name) > 4:
            positions = list(range(2, len(name) - 1))
            if positions:
                pos = random.choice(positions)
                name = name[:pos] + special_char + name[pos:]
        
        return name
    
    def _capitalize_name(self, name):
        """Применяет различные стили капитализации"""
        styles = [
            lambda x: x.lower(),  # все маленькие
            lambda x: x.upper(),  # все большие  
            lambda x: x.capitalize(),  # первая большая
            lambda x: x.title(),  # каждое слово с большой
            lambda x: ''.join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(x))  # чередование
        ]
        
        # Чаще используем нижний регистр (более натурально для никнеймов)
        weights = [0.5, 0.1, 0.2, 0.1, 0.1]
        style = random.choices(styles, weights=weights)[0]
        
        return style(name)
    
    def generate_nickname(self):
        """Генерирует один никнейм"""
        min_len = NICKNAME_GENERATOR['MIN_LENGTH']
        max_len = NICKNAME_GENERATOR['MAX_LENGTH']
        target_length = random.randint(min_len, max_len)
        
        # Генерируем базовое имя
        if random.choice([True, False]):
            name = self._generate_syllable_name(target_length)
        else:
            name = self._generate_word_combination(target_length)
        
        # Ограничиваем длину
        if len(name) > max_len:
            name = name[:max_len]
        elif len(name) < min_len:
            # Дополняем цифрами
            while len(name) < min_len:
                name += str(random.randint(0, 9))
        
        # Добавляем специальные символы
        name = self._add_special_chars(name)
        
        # Применяем капитализацию
        name = self._capitalize_name(name)
        
        # Финальная проверка длины после всех преобразований
        if len(name) > max_len:
            name = name[:max_len]
        
        return name
    
    def generate_nicknames(self, count=None):
        """Генерирует список уникальных никнеймов"""
        if count is None:
            count = NICKNAME_GENERATOR.get('QUANTITY', 10)
            
        nicknames = set()
        max_attempts = count * 10  # Избегаем бесконечного цикла
        attempts = 0
        
        while len(nicknames) < count and attempts < max_attempts:
            nickname = self.generate_nickname()
            nicknames.add(nickname)
            attempts += 1
        
        return list(nicknames)
    
    def save_nicknames_to_file(self, nicknames, filename='nicknames.txt'):
        """Сохраняет никнеймы в файл"""
        result_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'result')
        os.makedirs(result_dir, exist_ok=True)
        
        filepath = os.path.join(result_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                for nickname in nicknames:
                    f.write(f"{nickname}\n")
            
            log_success(f"✅ {len(nicknames)} никнеймов сохранено в {filepath}")
            return filepath
            
        except Exception as e:
            log_error(f"❌ Ошибка сохранения файла: {e}")
            return None


def generate_nicknames():
    """Основная функция для вызова из main.py"""
    try:
        log_info("🎭 Запуск генератора никнеймов")
        
        # Показываем настройки
        settings = NICKNAME_GENERATOR
        log_info(f"📋 Настройки:")
        log_info(f"   • Длина: {settings['MIN_LENGTH']}-{settings['MAX_LENGTH']} символов")
        log_info(f"   • Специальные символы: {'включены' if settings['USE_SPECIAL_CHARS'] else 'отключены'}")
        log_info(f"   • Количество: {settings['QUANTITY']} никнеймов")
        
        # Создаем генератор
        generator = NicknameGenerator()
        
        # Генерируем никнеймы
        log_info(f"🔄 Генерируем {settings['QUANTITY']} никнеймов...")
        nicknames = generator.generate_nicknames()
        
        # Показываем примеры
        log_info("📝 Примеры сгенерированных никнеймов:")
        for i, nickname in enumerate(nicknames[:5]):  # Показываем первые 5
            log_info(f"   {i+1}. {nickname}")
        
        if len(nicknames) > 5:
            log_info(f"   ... и еще {len(nicknames) - 5}")
        
        # Сохраняем в файл
        filepath = generator.save_nicknames_to_file(nicknames)
        
        if filepath:
            log_success(f"🎉 Генерация завершена! Файл: {os.path.basename(filepath)}")
        
        return nicknames
        
    except Exception as e:
        log_error(f"❌ Ошибка генерации никнеймов: {e}")
        return None


def main():
    """Точка входа для тестирования"""
    generate_nicknames()


if __name__ == "__main__":
    main()