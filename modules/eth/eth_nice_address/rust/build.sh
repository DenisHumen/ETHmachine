#!/bin/bash

# Build script для ETH Nice Address Generator (Rust)
# Автоматическая компиляция с оптимизацией

set -e

echo "======================================"
echo "  ETH Nice Address - Rust Builder"
echo "======================================"
echo ""

# Цвета
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Проверка Cargo
if ! command -v cargo &> /dev/null; then
    echo -e "${RED}❌ Cargo не найден!${NC}"
    echo ""
    echo "Установите Rust:"
    echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ Cargo найден: $(cargo --version)${NC}"
echo ""

# Переход в директорию проекта
cd "$(dirname "$0")"

# Опции сборки
BUILD_TYPE="${1:-release}"

if [ "$BUILD_TYPE" == "debug" ]; then
    echo -e "${YELLOW}Сборка в режиме DEBUG (быстрая компиляция)${NC}"
    cargo build
    BINARY_PATH="target/debug/eth_nice_address"
else
    echo -e "${GREEN}Сборка в режиме RELEASE (оптимизация)${NC}"
    echo -e "${YELLOW}Первая компиляция может занять 5-10 минут...${NC}"
    echo ""
    cargo build --release
    BINARY_PATH="target/release/eth_nice_address"
fi

echo ""
echo -e "${GREEN}✓ Компиляция завершена!${NC}"
echo ""
echo "Бинарник: $BINARY_PATH"
echo ""

# Информация о размере
if [ -f "$BINARY_PATH" ]; then
    SIZE=$(du -h "$BINARY_PATH" | cut -f1)
    echo -e "${GREEN}Размер: $SIZE${NC}"
fi

echo ""
echo "Запуск:"
echo "  ./$BINARY_PATH -n 10"
echo ""
echo "Справка:"
echo "  ./$BINARY_PATH --help"
echo ""
