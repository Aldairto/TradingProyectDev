from flask import Flask, request, jsonify
import requests
import os
import threading
import json

app = Flask(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Telegram: múltiples destinos (compat con single TOKEN/CHAT_ID)
# ──────────────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DESTINATIONS_ENV = os.environ.get("DESTINATIONS")  # '[{"token":"...","chat_id":"..."}, ...]'

TPS = [0.2, 0.5, 1, 2, 3, 5]  # TP1-TP6 en %
SL_BUY = 0.40
SL_SELL = 0.40


def _mask_token(tok: str, keep: int = 6) -> str:
    try:
        if not tok:
            return ""
        if len(tok) <= keep:
            return "*" * len(tok)
        return tok[:keep] + "…" + "*" * (max(0, len(tok) - keep - 1))
    except Exception:
        return "***"


def _safe_json_loads(txt: str):
    """
    Carga JSON tolerante a comillas simples y espacios.
    Si falla, devuelve None.
    """
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        # Intento suave: reemplazar comillas simples por dobles
        try:
            fixed = txt.replace("'", '"')
            return json.loads(fixed)
        except Exception:
            return None


def get_telegram_destinations():
    """
    Devuelve lista de destinos [{'token': '...', 'chat_id': '...'}, ...]
    Prioriza DESTINATIONS; si no existe, usa TELEGRAM_TOKEN + TELEGRAM_CHAT_ID.
    """
    dests = []
    data = _safe_json_loads(DESTINATIONS_ENV)
    if isinstance(data, list) and data:
        for item in data:
            tok = str(item.get("token", "")).strip()
            cid = str(item.get("chat_id", "")).strip()
            if tok and cid:
                dests.append({"token": tok, "chat_id": cid})
    # Fallback legacy
    if not dests and TELEGRAM_TOKEN and CHAT_ID:
        dests.append({"token": TELEGRAM_TOKEN.strip(), "chat_id": str(CHAT_ID).strip()})
    return dests


TELEGRAM_DESTINATIONS = get_telegram_destinations()
if TELEGRAM_DESTINATIONS:
    print("[TG] Destinos cargados:")
    for i, d in enumerate(TELEGRAM_DESTINATIONS, 1):
        print(f"   {i}) chat_id={d['chat_id']} token={_mask_token(d['token'])}")
else:
    print("[TG] Sin destinos: configura DESTINATIONS o TELEGRAM_TOKEN/TELEGRAM_CHAT_ID")


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


def _send_one_telegram(token: str, chat_id: str, message: str):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        print(f"[TG] -> chat_id={chat_id} status={r.status_code} resp={r.text[:200]}")
        return r.json()
    except Exception as e:
        print(f"[TG] Error chat_id={chat_id}:", e)
        return None


def send_telegram_message(message: str):
    """
    Envía a TODOS los destinos definidos. Si no hay destinos, imprime aviso.
    Esta función puede llamarse desde un thread de background.
    """
    if not TELEGRAM_DESTINATIONS:
        print("[TG] No hay destinos configurados; no se envía.")
        return None

    results = []
    for d in TELEGRAM_DESTINATIONS:
        res = _send_one_telegram(d["token"], d["chat_id"], message)
        results.append(res)
    return results


def _parse_json_from_raw(raw_text: str) -> dict:
    """Parsea JSON partiendo del raw (string). Evita re-leer el stream."""
    try:
        return json.loads(raw_text)
    except Exception as e:
        print("[WEBHOOK] json.loads error:", e)
        return {}


def _process_signal_async(data: dict):
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

        # Enviar a todos los destinos (ya estamos en background)
        send_telegram_message(msg)

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
            print("[WEBHOOK] Payload incompleto. No se inserta:",
                  {"signal": order_type_raw, "symbol": symbol, "price": price})

    except Exception as e:
        print("[WEBHOOK] Error en procesamiento async:", e)


@app.post("/webhook")
def webhook():
    """Recibe la señal; responde de inmediato y procesa en background (evita 502)."""
    try:
        # ¡IMPORTANTE!: cache=True para NO consumir el stream (lo reutilizamos)
        raw_text = request.get_data(cache=True, as_text=True)
        print("[WEBHOOK] raw body:", raw_text)

        # Usar primero get_json (si el header viene bien); si no, parsear el raw ya leído
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data:
            data = _parse_json_from_raw(raw_text)

        threading.Thread(target=_process_signal_async, args=(data,), daemon=True).start()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print("[WEBHOOK] handler error:", e)
        return jsonify({"status": "ok"}), 200


# Utilidad de debug
@app.post("/echo")
def echo():
    raw = request.get_data(cache=True, as_text=True)
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
