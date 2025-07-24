from flask import Flask, request, jsonify
import os
import threading
import requests
import time
import json

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TPS = [0.2, 0.5, 1, 2, 3, 5]
SL_BUY = 0.40
SL_SELL = 0.40

ORDERS_FILE = "data/pending_orders.json"  # Carpeta local, ajústalo si es necesario

def calcular_tps_sl(price, tps, sl, side="buy"):
    niveles = {}
    if side == "buy":
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 + tp / 100), 2)
        niveles["SL"] = round(price * (1 - sl / 100), 2)
    else:
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

def guardar_orden_mt5(orden):
    os.makedirs(os.path.dirname(ORDERS_FILE), exist_ok=True)
    # Agrega la orden como línea nueva en JSONL (uno por línea)
    with open(ORDERS_FILE, "a") as f:
        f.write(json.dumps(orden) + "\n")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Alerta recibida:", data)

    if isinstance(data, dict):
        side = data.get("signal", "").lower()
        price = data.get("price", 0)
        try:
            price = float(price)
        except Exception:
            price = 0
        symbol = data.get("symbol", "???")

        # Lógica para señales
        if price > 0:
            if "buy/compra normal" in side:
                sl = SL_BUY
                niveles = calcular_tps_sl(price, TPS, sl, side="buy")
                emoji = "📈"
                tipo = "COMPRA CONFIRMADA"
                # --- Guardar orden para executor MT5
                orden_para_mt5 = {
                    "side": "buy",
                    "price": price,
                    "symbol": symbol,
                    "tps": niveles,
                    "timestamp": time.time()
                }
                guardar_orden_mt5(orden_para_mt5)
            elif "sell/venta normal" in side:
                sl = SL_SELL
                niveles = calcular_tps_sl(price, TPS, sl, side="sell")
                emoji = "📉"
                tipo = "VENTA CONFIRMADA"
                orden_para_mt5 = {
                    "side": "sell",
                    "price": price,
                    "symbol": symbol,
                    "tps": niveles,
                    "timestamp": time.time()
                }
                guardar_orden_mt5(orden_para_mt5)
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
                    msg += f"🎯 TP{i}: {niveles.get(f'TP{i}')}\n"
                msg += f"🛡️ SL: {niveles.get('SL')}\n"
        else:
            msg = f"Alerta TradingView:\n{data}"
    else:
        msg = f"Alerta TradingView (mensaje simple):\n{data}"

    threading.Thread(target=send_telegram_message, args=(msg,)).start()
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return "¡Bot de Trading activo! Versión Railway."

if __name__ == "__main__":
    app.run(port=5000, host="0.0.0.0")
