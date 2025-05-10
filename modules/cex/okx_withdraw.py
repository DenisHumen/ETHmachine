import random
import time
from okx.Trade import TradeAPI
import okx.Account as Account
import csv
import os

ALLOWED_CHAINS = {
    "USDT": ["TRX"],
    "ETH": ["OP", "ARB", "BASE"],
    "G": ["GRAVITY"]
}

def withdraw_from_okx(api_key, api_secret, passphrase, token, sum_range, address, network, random_sleep, eu_type):
    token = token.upper()
    network = network.upper()

    if token not in ALLOWED_CHAINS or network not in ALLOWED_CHAINS[token]:
        raise ValueError(f"Недопустимая комбинация токена и сети: {token} - {network}")

    chain_param = f"{token}-{network}"

    trade = TradeAPI(
        api_key=api_key,
        api_secret_key=api_secret,
        passphrase=passphrase,
        use_server_time=False,
        flag=eu_type
    )

    if len(sum_range) != 2:
        raise ValueError("Параметр sum_range должен содержать только два значения: [min, max]")

    amount = str(round(random.uniform(sum_range[0], sum_range[1]), 6)) 

    client_id = f"wd_{int(time.time())}"

    withdrawal_params = {
        "ccy": token,
        "amt": amount,
        "dest": "3", 
        "toAddr": address,
        "chain": chain_param,
        "fee": "0",  
        "clientId": client_id
    }

    print(f"Отправка {amount} {token} через {chain_param} на {address}")
    try:
        result = trade.withdrawal(withdrawal_params)
        print("✅ Ответ OKX:", result)

        if random_sleep:
            sleep_time = random.randint(random_sleep[0], random_sleep[1])
            print(f"⏳ Задержка {sleep_time} сек...")
            time.sleep(sleep_time)

        return result
    except Exception as e:
        print("❌ Ошибка при выводе:", str(e))
        return {"error": str(e)}




def get_balances_okx(api_key, api_secret, passphrase, flag="0", output_file="result/result.csv"):
    try:
        accountAPI = Account.AccountAPI(api_key, api_secret, passphrase, False, flag)

        balances = accountAPI.get_account_balance()

        if "data" not in balances or not balances["data"]:
            print("❌ Нет данных для сохранения.")
            return balances

        details = balances["data"][0]["details"]

        sorted_details = sorted(details, key=lambda x: float(x["eqUsd"]), reverse=True)

        headers = ["Currency", "Available Balance", "Total Balance", "USD Equivalent"]
        rows = [
            {
                "Currency": item["ccy"],
                "Available Balance": item["availBal"],
                "Total Balance": item["eq"],
                "USD Equivalent": item["eqUsd"]
            }
            for item in sorted_details
        ]

        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        with open(output_file, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

        print(f"✅ Данные успешно сохранены в {output_file}")
        return balances
    except Exception as e:
        print(f"❌ Ошибка при получении или сохранении балансов: {str(e)}")
        return {"error": str(e)}