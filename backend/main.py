from flask import Flask, request, jsonify
import requests
import os
import threading
from db import insert_order, get_active_counts, get_db  # helpers del backend

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
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        print("Respuesta de Telegram:", r.status_code, r.text)
        return r.json()
    except Exception as e:
        print("Error al enviar mensaje a Telegram:", e)
        return None

def _process_signal_async(data):
    """Procesa la señal en background (fan-out + Telegram)."""
    try:
        # --- 1) Normaliza payload sin cambiar llaves de TradingView ---
        order_type_raw = str((data or {}).get("signal", "")).strip()
        symbol_in      = str((data or {}).get("symbol", "")).strip()
        price_raw      = (data or {}).get("price", 0)

        # Normaliza símbolo ("BINANCE:BTCUSD" -> "BTCUSD", "XUAUSD" -> "XAUUSD")
        symbol = symbol_in.split(":")[-1].upper()
        if symbol == "XUAUSD":
            symbol = "XAUUSD"

        try:
            price = float(price_raw)
        except Exception as e:
            print("Error al convertir price a float:", e)
            price = 0.0

        # --- 2) Mensaje a Telegram (bonito) ---
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

        msg = f"{emoji} <b>{tipo}</b> en {symbol}\n• Precio de entrada: <b>{price}</b>\n"
        if niveles:
            for i in range(1, 7):
                msg += f"🎯 TP{i}: {niveles.get(f'TP{i}')}\n"
            msg += f"🛡️ SL: {niveles.get('SL')}\n"
        threading.Thread(target=send_telegram_message, args=(msg,), daemon=True).start()

        # --- 3) Fan-out: inserta una orden 'pending' por CADA cuenta activa ---
        if price > 0.0 and symbol and order_type_raw:
            try:
                active_accounts = get_active_counts()
                inserted = 0
                for acc_login in active_accounts:
                    insert_order(
                        order_type=order_type_raw,
                        price=price,
                        symbol=symbol,
                        account_login=str(acc_login),
                        status='pending'
                    )
                    inserted += 1
                print(f"[WEBHOOK] Órdenes insertadas (fan-out): {inserted}")
            except Exception as e:
                print(f"[WEBHOOK] Error fan-out: {e}")

    except Exception as e:
        print(f"[WEBHOOK] Error en procesamiento async: {e}")

@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True, force=True)
    # Procesa en segundo plano y responde YA (evita 502)
    threading.Thread(target=_process_signal_async, args=(data,), daemon=True).start()
    return jsonify({"status": "ok"})

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/dbcheck")
def dbcheck():
    try:
        conn = get_db(); conn.close()
        return {"db": "ok"}
    except Exception as e:
        return {"db": "error", "msg": str(e)}, 500

@app.get("/")
def index():
    return "¡Bot de Trading activo! Versión Railway + MySQL (backend/)"

if __name__ == "__main__":
    # Para correr local sin gunicorn
    app.run(port=int(os.getenv("PORT", "5000")), host="0.0.0.0")
