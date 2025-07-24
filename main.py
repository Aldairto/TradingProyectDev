from flask import Flask, request, jsonify
import requests
import os
import threading
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Configuración de niveles TP y SL
TPS = [0.2, 0.5, 1, 2, 3, 5]  # TP1-TP6 (%)
SL_BUY = 0.40                  # SL para compras (%)
SL_SELL = 0.40                 # SL para ventas (%)

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
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    r = requests.post(url, json=payload)
    print("Respuesta de Telegram:", r.status_code, r.text)
    return r.json()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Alerta recibida:", data)

    # Normaliza el signal
    signal_raw = data.get("signal", "").lower().strip()
    price = data.get("price", 0)
    try:
        price = float(price)
    except Exception as e:
        print("Error al convertir price a float:", e)
        price = 0
    symbol = data.get("symbol", "???")

    msg = None

    # Analiza el tipo de señal
    if "posible buy" in signal_raw:
        emoji = "🔵"
        msg = f"""{emoji} <b>POSIBLE BUY</b> detectado en {symbol}
• Precio observado: {price}
(Revisa confirmación antes de operar)
"""
    elif "posible sell" in signal_raw:
        emoji = "🟠"
        msg = f"""{emoji} <b>POSIBLE SELL</b> detectado en {symbol}
• Precio observado: {price}
(Revisa confirmación antes de operar)
"""
    elif "buy" in signal_raw:
        sl = SL_BUY
        niveles = calcular_tps_sl(price, TPS, sl, "buy")
        emoji = "📈"
        msg = f"""{emoji} <b>COMPRA (BUY)</b> en {symbol}
• Precio de entrada: {price}
• TP1: {niveles['TP1']}
• TP2: {niveles['TP2']}
• TP3: {niveles['TP3']}
• TP4: {niveles['TP4']}
• TP5: {niveles['TP5']}
• TP6: {niveles['TP6']}
• SL: {niveles['SL']}
"""
    elif "sell" in signal_raw:
        sl = SL_SELL
        niveles = calcular_tps_sl(price, TPS, sl, "sell")
        emoji = "📉"
        msg = f"""{emoji} <b>VENTA (SELL)</b> en {symbol}
• Precio de entrada: {price}
• TP1: {niveles['TP1']}
• TP2: {niveles['TP2']}
• TP3: {niveles['TP3']}
• TP4: {niveles['TP4']}
• TP5: {niveles['TP5']}
• TP6: {niveles['TP6']}
• SL: {niveles['SL']}
"""
    else:
        msg = f"Alerta TradingView:\n{data}"

    threading.Thread(target=send_telegram_message, args=(msg,)).start()
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(port=5000, host="0.0.0.0")
