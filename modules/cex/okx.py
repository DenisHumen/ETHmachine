import random
import time
from okx import Trade
from data import cex_settings as cfg

# Допустимые комбинации токенов и сетей
ALLOWED_CHAINS = {
    "USDT": ["TRX"],
    "ETH": ["OP", "ARB", "BASE"],
    "G": ["GRAVITY"]
}

def withdraw_from_okx():
    """
    Производит вывод криптовалюты с учётом параметров из settings.
    """
    # Проверка на заполненные значения
    required_fields = [
        cfg.OKX_API_KEY, cfg.OKX_API_SECRET, cfg.OKX_API_PASSPHRAS,
        cfg.TOKEN_OUT, cfg.SUM, cfg.WITHDRAW_ADDRESS, cfg.WITHDRAW_NETWORK
    ]

    if not all(required_fields):
        raise ValueError("Не все параметры настроек заполнены. Проверьте cex_settings.py")

    token = cfg.TOKEN_OUT.upper()
    network = cfg.WITHDRAW_NETWORK.upper()

    # Проверка допустимости комбинации токена и сети
    if token not in ALLOWED_CHAINS or network not in ALLOWED_CHAINS[token]:
        raise ValueError(f"Недопустимая комбинация токена и сети: {token} - {network}")

    # Формирование параметра chain
    chain_param = f"{token}-{network}"

    # Подключение к OKX
    trade = Trade(
        api_key=cfg.OKX_API_KEY,
        api_secret_key=cfg.OKX_API_SECRET,
        passphrase=cfg.OKX_API_PASSPHRAS,
        use_server_time=False,
        flag=cfg.OKX_EU_TYPE
    )

    if len(cfg.SUM) != 2:
        raise ValueError("Параметр SUM должен содержать только два значения: [min, max]")

    amount = str(round(random.uniform(cfg.SUM[0], cfg.SUM[1]), 6))  # до 6 знаков после запятой

    # Уникальный ID
    client_id = f"wd_{int(time.time())}"

    # Параметры вывода
    withdrawal_params = {
        "ccy": token,
        "amt": amount,
        "dest": "3",  # внешний адрес
        "toAddr": cfg.WITHDRAW_ADDRESS,
        "chain": chain_param,
        "fee": "0",  # можно обновить на нужное значение
        "clientId": client_id
    }

    print(f"Отправка {amount} {token} через {chain_param} на {cfg.WITHDRAW_ADDRESS}")
    try:
        result = trade.withdrawal(withdrawal_params)
        print("✅ Ответ OKX:", result)

        # Случайная задержка между операциями
        if cfg.RANDON_SLEEP:
            sleep_time = random.randint(cfg.RANDON_SLEEP[0], cfg.RANDON_SLEEP[1])
            print(f"⏳ Задержка {sleep_time} сек...")
            time.sleep(sleep_time)

        return result
    except Exception as e:
        print("❌ Ошибка при выводе:", str(e))
        return {"error": str(e)}
