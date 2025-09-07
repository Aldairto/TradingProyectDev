from flask import Flask, request, jsonify
import requests
import os
import threading
import json

app = Flask(__name__)

# Telegram (opcional)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TPS = [0.2, 0.5, 1, 2, 3, 5]  # TP1-TP6 en %
SL_BUY = 0.40
SL_SELL = 0.40


def _to_float(x):
    try:
        if isinstance(x, str):
            x = x.replace(",", "").strip()
        return float(x)
    except Exception:
        return 0.0


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
        print("[TG] Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID (no se envía).")
        return None
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        print("[TG] Respuesta:", r.status_code, r.text)
        return r.json()
    except Exception as e:
        print("[TG] Error al enviar:", e)
        return None


def _safe_parse_json_from_request(req) -> dict:
    """Intenta parsear JSON; si falla usa el raw body como fallback."""
    try:
        data = req.get_json(silent=True)
        if data is not None:
            return data
    except Exception as e:
        print("[WEBHOOK] get_json error:", e)

    try:
        raw = req.get_data(cache=False)
        if not raw:
            return {}
        # intenta decodificar como UTF-8
        decoded = raw.decode("utf-8", errors="ignore")
        return json.loads(decoded)
    except Exception as e:
        print("[WEBHOOK] Fallback json.loads error:", e)
        return {}


def _process_signal_async(data):
    """Procesa la señal en segundo plano: normaliza, fan-out e informa a Telegram."""
    try:
        print("[WEBHOOK] data parseada:", data)

        # 1) Normaliza payload
        order_type_raw = str((data or {}).get("signal", "")).strip()
        symbol_in      = str((data or {}).get("symbol", "")).strip()
        price          = _to_float((data or {}).get("price", 0))

        # Normaliza símbolo: "BINANCE:BTCUSD" -> "BTCUSD"; corrige XUAUSD
        symbol = symbol_in.split(":")[-1].upper()
        if symbol == "XUAUSD":
            symbol = "XAUUSD"

        # 2) Telegram (decorativo)
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
                val = niveles.get(f"TP{i}")
                if val is not None:
                    msg += f"🎯 TP{i}: {val}\n"
            if "SL" in niveles:
                msg += f"🛡️ SL: {niveles['SL']}\n"
        threading.Thread(target=send_telegram_message, args=(msg,), daemon=True).start()

        # 3) Fan-out a cuentas activas
        if price > 0.0 and symbol and order_type_raw:
            try:
                from db import insert_order, get_active_counts  # import perezoso
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
    """Recibe la señal; responde de inmediato y procesa en background (evita 502)."""
    try:
        raw = request.get_data(cache=False, as_text=True)
        print("[WEBHOOK] raw body:", raw)
        data = _safe_parse_json_from_request(request)
        threading.Thread(target=_process_signal_async, args=(data,), daemon=True).start()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print("[WEBHOOK] handler error:", e)
        return jsonify({"status": "ok"}), 200


# Utilidad de debug
@app.post("/echo")
def echo():
    raw = request.get_data(cache=False, as_text=True)
    return jsonify({"raw": raw})


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/dbcheck")
def dbcheck():
    try:
        from db import get_db  # import perezoso
        conn = get_db(); conn.close()
        return {"db": "ok"}
    except Exception as e:
        return {"db": "error", "msg": str(e)}, 500


@app.get("/")
def index():
    return "ok"


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"[BOOT] starting Flask on 0.0.0.0:{port} pid={os.getpid()}", flush=True)
    app.run(host="0.0.0.0", port=port)
