from flask import Flask, request, jsonify
import requests
import os
import threading
from db import insert_order   # <-- Importa la función de db.py

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TPS = [0.2, 0.5, 1, 2, 3, 5]  # TP1-TP6 (%)
SL_BUY = 0.40
SL_SELL = 0.40

def calcular_tps_sl(price, tps, sl, side="buy"):
    niveles = {}
    if side == "buy":
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 + tp / 100), 2)
        niveles["SL"] = round(price * (1 - sl / 100), 2)
    else:  # sell
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 - tp / 100), 2)
        niveles["SL"] = round(price * (1 + sl / 100), 2)
    return niveles

def send_telegram_message(message: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("ERROR: Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload)
        print("Respuesta de Telegram:", r.status_code, r.text)
        return r.json()
    except Exception as e:
        print("Error al enviar mensaje a Telegram:", e)
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Alerta recibida:", data)

    if isinstance(data, dict):
        side = data.get("signal", "").lower()
        price = data.get("price", 0)
        try:
            price = float(price)
        except Exception as e:
            print("Error al convertir price a float:", e)
            price = 0
        symbol = data.get("symbol", "???")

        # Guarda en MySQL
        if price > 0:
            # Usa "order_type" como columna
            threading.Thread(target=insert_order, args=(side, price, symbol)).start()

            # Señales confirmadas (calcula TP/SL)
            if "buy/compra normal" in side:
                sl = SL_BUY
                niveles = calcular_tps_sl(price, TPS, sl, side="buy")
                emoji = "📈"
                tipo = "COMPRA CONFIRMADA"
            elif "sell/venta normal" in side:
                sl = SL_SELL
                niveles = calcular_tps_sl(price, TPS, sl, side="sell")
                emoji = "📉"
                tipo = "VENTA CONFIRMADA"
            elif "posible buy" in side:
                emoji = "🟡"
                tipo = "POSIBLE COMPRA"
                niveles = None
            elif "posible sell" in side:
                emoji = "🟠"
                tipo = "POSIBLE VENTA"
                niveles = None
            else:
                emoji = "❓"
                tipo = "SEÑAL DESCONOCIDA"
                niveles = None

            msg = f"""{emoji} <b>{tipo}</b> en {symbol}
• Precio de entrada: <b>{price}</b>
"""
            if niveles:
                for i in range(1, 7):
                    msg += f"🎯 TP{i}: {niveles[f'TP{i}']}\n"
                msg += f"🛡️ SL: {niveles['SL']}\n"
        else:
            msg = f"Alerta TradingView:\n{data}"
    else:
        msg = f"Alerta TradingView (mensaje simple):\n{data}"

    threading.Thread(target=send_telegram_message, args=(msg,)).start()
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return "¡Bot de Trading activo! Versión Railway + MySQL"

if __name__ == "__main__":
    app.run(port=5000, host="0.0.0.0")
