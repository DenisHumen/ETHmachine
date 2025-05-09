import random
import time
from okx import Trade

# Допустимые комбинации токенов и сетей
ALLOWED_CHAINS = {
    "USDT": ["TRX"],
    "ETH": ["OP", "ARB", "BASE"],
    "G": ["GRAVITY"]
}

def withdraw_from_okx(api_key, api_secret, passphrase, token, sum_range, address, network, random_sleep, eu_type):
    """
    Производит вывод криптовалюты с учётом переданных параметров.

    Args:
        api_key (str): OKX API key.
        api_secret (str): OKX API secret.
        passphrase (str): OKX API passphrase.
        token (str): Токен для вывода.
        sum_range (list): Диапазон суммы для вывода [min, max].
        address (str): Адрес для вывода.
        network (str): Сеть для вывода.
        random_sleep (list): Диапазон случайной задержки [min, max].
        eu_type (int): Тип аккаунта (0 или 1).

    Returns:
        dict: Результат операции вывода.
    """
    token = token.upper()
    network = network.upper()

    # Проверка допустимости комбинации токена и сети
    if token not in ALLOWED_CHAINS or network not in ALLOWED_CHAINS[token]:
        raise ValueError(f"Недопустимая комбинация токена и сети: {token} - {network}")

    # Формирование параметра chain
    chain_param = f"{token}-{network}"

    # Подключение к OKX
    trade = Trade(
        api_key=api_key,
        api_secret_key=api_secret,
        passphrase=passphrase,
        use_server_time=False,
        flag=eu_type
    )

    if len(sum_range) != 2:
        raise ValueError("Параметр sum_range должен содержать только два значения: [min, max]")

    amount = str(round(random.uniform(sum_range[0], sum_range[1]), 6))  # до 6 знаков после запятой

    # Уникальный ID
    client_id = f"wd_{int(time.time())}"

    # Параметры вывода
    withdrawal_params = {
        "ccy": token,
        "amt": amount,
        "dest": "3",  # внешний адрес
        "toAddr": address,
        "chain": chain_param,
        "fee": "0",  # можно обновить на нужное значение
        "clientId": client_id
    }

    print(f"Отправка {amount} {token} через {chain_param} на {address}")
    try:
        result = trade.withdrawal(withdrawal_params)
        print("✅ Ответ OKX:", result)

        # Случайная задержка между операциями
        if random_sleep:
            sleep_time = random.randint(random_sleep[0], random_sleep[1])
            print(f"⏳ Задержка {sleep_time} сек...")
            time.sleep(sleep_time)

        return result
    except Exception as e:
        print("❌ Ошибка при выводе:", str(e))
        return {"error": str(e)}
