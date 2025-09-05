from flask import Flask, request, jsonify
import requests
import os
import threading
from db import insert_order, get_active_counts   # <-- importa el nuevo helper

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

    # 1) Lee y normaliza el payload SIN cambiar el formato que te manda TradingView
    order_type_raw = str((data or {}).get("signal", "")).strip()           # p.ej. "Buy/Compra Normal o Smart"
    symbol_in      = str((data or {}).get("symbol", "")).strip()           # p.ej. "XAUUSD" o "BINANCE:BTCUSDTPERP"
    price_raw      = (data or {}).get("price", 0)

    # Normaliza símbolo: toma la última parte y mayúsculas (XUAUSD -> XAUUSD opcional)
    symbol = symbol_in.split(":")[-1].upper()
    if symbol == "XUAUSD":   # typo común
        symbol = "XAUUSD"

    try:
        price = float(price_raw)
    except Exception as e:
        print("Error al convertir price a float:", e)
        price = 0.0

    # 2) Publica al Telegram (mensaje amigable) - reusa tu lógica actual
    msg = f"Alerta TradingView:\n{data}"
    side_lc = order_type_raw.lower()
    niveles = None
    if "buy/compra normal" in side_lc:
        niveles = calcular_tps_sl(price, TPS, SL_BUY, side="buy")
        emoji = "📈"; tipo = "COMPRA CONFIRMADA"
    elif "sell/venta normal" in side_lc:
        niveles = calcular_tps_sl(price, TPS, SL_SELL, side="sell")
        emoji = "📉"; tipo = "VENTA CONFIRMADA"
    elif "posible buy" in side_lc:
        emoji = "🟡"; tipo = "POSIBLE COMPRA"
    elif "posible sell" in side_lc:
        emoji = "🟠"; tipo = "POSIBLE VENTA"
    elif "take profit buy" in side_lc or "take profit long" in side_lc:
        emoji = "🎯"; tipo = "TAKE PROFIT BUY"
    elif "take profit sell" in side_lc or "take profit short" in side_lc:
        emoji = "🎯"; tipo = "TAKE PROFIT SELL"
    else:
        emoji = "❓"; tipo = "SEÑAL DESCONOCIDA"

    if price > 0.0 and symbol:
        msg = f"""{emoji} <b>{tipo}</b> en {symbol}
• Precio de entrada: <b>{price}</b>
"""
        if niveles:
            for i in range(1, 7):
                msg += f"🎯 TP{i}: {niveles[f'TP{i}']}\n"
            msg += f"🛡️ SL: {niveles['SL']}\n"

    threading.Thread(target=send_telegram_message, args=(msg,)).start()

    # 3) FAN-OUT: inserta una orden 'pending' por CADA cuenta activa de counts.enabled=1
    if price > 0.0 and symbol and order_type_raw:
        try:
            active_accounts = get_active_counts()  # <- lee counts.enabled=1
            inserted = 0
            for acc_login in active_accounts:
                # insert_order() ya existe en tu db.py y admite account_login
                insert_order(order_type=order_type_raw, price=price, symbol=symbol,
                             account_login=str(acc_login), status='pending')
                inserted += 1
            print(f"[WEBHOOK] Órdenes insertadas (fan-out): {inserted}")
        except Exception as e:
            print(f"[WEBHOOK] Error fan-out: {e}")

    return jsonify({"status": "ok"})


@app.route("/")
def index():
    return "¡Bot de Trading activo! Versión Railway + MySQL"


if __name__ == "__main__":
    app.run(port=5000, host="0.0.0.0")
