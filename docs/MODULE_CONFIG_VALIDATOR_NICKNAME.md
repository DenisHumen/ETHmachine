# 🔧 Валидация настроек NICKNAME_GENERATOR

В модуль `modules/config_validator.py` добавлена проверка настроек генератора никнеймов.

## ✅ Что проверяется

### 1. MIN_LENGTH (минимальная длина)
- **Ошибки:**
  - Пустое значение (`None`, `''`)
  - Неверный тип данных (не `int`)
  - Значение < 1
- **Предупреждения:**
  - Значение < 3 (слишком мал)
  - Значение > 20 (слишком большой)

### 2. MAX_LENGTH (максимальная длина)
- **Ошибки:**
  - Пустое значение (`None`, `''`)
  - Неверный тип данных (не `int`) 
  - Значение < 1
- **Предупреждения:**
  - Значение > 50 (слишком большой)

### 3. USE_SPECIAL_CHARS (использование символов)
- **Ошибки:**
  - Пустое значение (`None`, `''`)
  - Неверный тип данных (не `bool`)

### 4. QUANTITY (количество никнеймов)
- **Ошибки:**
  - Пустое значение (`None`, `''`) 
  - Неверный тип данных (не `int`)
  - Значение < 1
- **Предупреждения:**
  - Значение > 100000 (может занять много времени)

### 5. Соотношения значений
- **Ошибки:**
  - MIN_LENGTH > MAX_LENGTH
- **Предупреждения:**
  - MAX_LENGTH - MIN_LENGTH > 30 (слишком большой диапазон)

## 🚀 Использование

### Автоматическая проверка
```python
from modules.config_validator import ConfigValidator

validator = ConfigValidator()
is_valid = validator.validate_all()  # проверяет все настройки включая NICKNAME_GENERATOR
```

### Проверка только генератора никнеймов
```python
from modules.config_validator import ConfigValidator
from config.modules.cfg_generators import NICKNAME_GENERATOR

validator = ConfigValidator()
validator._validate_nickname_generator(NICKNAME_GENERATOR)

# Результаты
print(f"Ошибок: {len(validator.errors)}")
print(f"Предупреждений: {len(validator.warnings)}")
```

## 📋 Примеры ошибок и предупреждений

### ❌ Ошибки
```
❌ NICKNAME_GENERATOR['MIN_LENGTH'] не может быть пустым
❌ NICKNAME_GENERATOR['MAX_LENGTH'] должен быть положительным числом  
❌ NICKNAME_GENERATOR['USE_SPECIAL_CHARS'] должен быть True или False
❌ NICKNAME_GENERATOR['MIN_LENGTH'] не может быть больше MAX_LENGTH
```

### ⚠️ Предупреждения
```
⚠️ NICKNAME_GENERATOR['MIN_LENGTH'] слишком мал (рекомендуется >= 3)
⚠️ NICKNAME_GENERATOR['MAX_LENGTH'] слишком большой (рекомендуется <= 50)
⚠️ NICKNAME_GENERATOR['QUANTITY'] очень большой (может занять много времени)
⚠️ Слишком большой диапазон длины никнеймов (рекомендуется <= 30)
```

## 🔄 Обратная совместимость

Валидатор корректно обрабатывает ситуацию когда `NICKNAME_GENERATOR` отсутствует в старых конфигах:
```
⚠️ NICKNAME_GENERATOR не найден в конфиге (добавьте настройки для генератора никнеймов)
```

## 📊 Тестирование

Валидатор протестирован на следующих сценариях:
- ✅ Корректные настройки
- ✅ Пустые/None значения
- ✅ Неверные типы данных  
- ✅ Неверные диапазоны значений
- ✅ Экстремальные значения
- ✅ Отсутствие настроек (обратная совместимость)