from flask import Flask, request, jsonify
import requests
import os
import threading
from db import insert_order, get_active_counts, get_db  # helpers en backend/db.py

app = Flask(__name__)

# Variables para Telegram (configúralas en Railway → Variables)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Niveles por defecto (si quieres mostrarlos en el mensaje a Telegram)
TPS = [0.2, 0.5, 1, 2, 3, 5]  # TP1-TP6 en %
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
        print("[TG] Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID (no se envía mensaje).")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        print("[TG] Respuesta:", r.status_code, r.text)
        return r.json()
    except Exception as e:
        print("[TG] Error al enviar mensaje:", e)
        return None


def _process_signal_async(data):
    """Procesa la señal en segundo plano: normaliza, fan-out a cuentas e informa a Telegram."""
    try:
        # 1) Normaliza el payload (no cambies las llaves que manda TradingView)
        order_type_raw = str((data or {}).get("signal", "")).strip()
        symbol_in      = str((data or {}).get("symbol", "")).strip()
        price_raw      = (data or {}).get("price", 0)

        # Normaliza símbolo: "BINANCE:BTCUSDTPERP" -> "BTCUSDTPERP", corrige typo XUAUSD
        symbol = symbol_in.split(":")[-1].upper()
        if symbol == "XUAUSD":
            symbol = "XAUUSD"

        try:
            price = float(price_raw)
        except Exception as e:
            print("[WEBHOOK] price no numérico:", price_raw, "| error:", e)
            price = 0.0

        # 2) Mensaje a Telegram (decorativo)
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
            emoji = "❓"; tipo = "SEÑAL"

        msg = f"{emoji} <b>{tipo}</b> en {symbol}\n• Precio de entrada: <b>{price}</b>\n"
        if niveles:
            for i in range(1, 7):
                if f"TP{i}" in niveles:
                    msg += f"🎯 TP{i}: {niveles[f'TP{i}']}\n"
            if "SL" in niveles:
                msg += f"🛡️ SL: {niveles['SL']}\n"

        threading.Thread(target=send_telegram_message, args=(msg,), daemon=True).start()

        # 3) Fan-out: inserta una orden 'pending' por CADA cuenta activa en counts
        if price > 0.0 and symbol and order_type_raw:
            try:
                active_accounts = get_active_counts()
                print(f"[WEBHOOK] Cuentas activas: {active_accounts}")
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
                print(f"[WEBHOOK] Error fan-out:", e)
        else:
            print("[WEBHOOK] Payload incompleto. No se inserta:", {"signal": order_type_raw, "symbol": symbol, "price": price})

    except Exception as e:
        print("[WEBHOOK] Error en procesamiento async:", e)


@app.post("/webhook")
def webhook():
    """Recibe la señal; responde de inmediato y procesa en background para evitar 502."""
    try:
        raw = request.get_data(cache=False, as_text=True)
        print("[WEBHOOK] raw body:", raw)

        try:
            data = request.get_json(silent=True)
        except Exception as e:
            print("[WEBHOOK] JSON parse error:", e)
            data = None

        threading.Thread(target=_process_signal_async, args=(data,), daemon=True).start()
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("[WEBHOOK] handler error:", e)
        # Aun con error en handler devolvemos OK para no provocar 502
        return jsonify({"status": "ok"}), 200


@app.post("/echo")
def echo():
    """Devuelve lo que recibe; útil para depurar headers/body desde Postman."""
    try:
        raw = request.get_data(cache=False, as_text=True)
        print("[ECHO] raw body:", raw)
        return jsonify({"ok": True, "raw": raw}), 200
    except Exception as e:
        print("[ECHO] error:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/dbcheck")
def dbcheck():
    try:
        conn = get_db()
        conn.close()
        return {"db": "ok"}
    except Exception as e:
        return {"db": "error", "msg": str(e)}, 500


@app.get("/")
def index():
    return "¡Bot de Trading activo! Versión Railway + MySQL (backend/)"


if __name__ == "__main__":
    # Para pruebas locales (en Railway corre con gunicorn desde Procfile)
    app.run(port=int(os.getenv("PORT", "5000")), host="0.0.0.0")
