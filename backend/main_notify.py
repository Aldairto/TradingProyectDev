# main_notify.py
import os, json, logging, unicodedata, re
from flask import Flask, request, jsonify
import requests

# ==== CONFIG POR ENTORNO ====
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]          # token de @BotFather
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]      # -100... de tu canal
TRADINGVIEW_SECRET = os.environ.get("TRADINGVIEW_SECRET", "")  # opcional

# Solo notificaciones; símbolos permitidos (agrega los que uses)
ALLOWED_SYMBOLS = {"XAGUSD", "XAUUSD", "BTCUSD", "EURUSD"}

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')


# ---------------- Utilidades ----------------
def _strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def classify_signal(signal_raw: str) -> str:
    """
    Devuelve una etiqueta canónica en base a cadenas fijas como:
    - "Sell/Venta Normal o Smart"
    - "Buy/Compra Normal o Smart"
    (Puedes extender con más patrones si luego los necesitas)
    """
    if not signal_raw:
        return "UNKNOWN"
    t = _strip_accents(signal_raw).lower().strip()
    # Quitar espacios raros
    t = re.sub(r'\s+', ' ', t)

    # Coincidencia EXACTA o flexible con separadores "/", " - ", etc.
    # SELL / VENTA
    if re.search(r'^(sell|venta)\s*/?\s*(venta|sell)?\s*normal\s*o\s*smart$', t):
        return "SELL_NORMAL_SMART"
    # BUY / COMPRA
    if re.search(r'^(buy|compra)\s*/?\s*(compra|buy)?\s*normal\s*o\s*smart$', t):
        return "BUY_NORMAL_SMART"

    # Si quieres añadir TPs más adelante, ej.:
    # if re.search(r'^take\s*profit.*sell', t) or re.search(r'^tp.*sell', t):
    #     return "TP_SELL"
    # if re.search(r'^take\s*profit.*buy', t) or re.search(r'^tp.*buy', t):
    #     return "TP_BUY"

    return "UNKNOWN"

def send_to_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code != 200:
        app.logger.error(f"[TG] {r.status_code}: {r.text}")

def format_message(symbol: str, signal_raw: str, price):
    label = classify_signal(signal_raw)

    if label == "SELL_NORMAL_SMART":
        emo = "📉"
        title = "Sell / Venta (Normal o Smart)"
    elif label == "BUY_NORMAL_SMART":
        emo = "📈"
        title = "Buy / Compra (Normal o Smart)"
    else:
        emo = "ℹ️"
        title = signal_raw  # muestra el texto tal cual si no se clasificó

    price_txt = f"{price}" if price is not None else "—"
    # Mensaje compacto, listo para canal
    return f"{emo} <b>{symbol}</b> — {title}\n💵 Precio: <b>{price_txt}</b>"

# ---------------- Endpoints ----------------
@app.get("/")
def root():
    return "OK", 200

@app.post("/webhook")
def webhook():
    # 1) Valida secret (opcional). Puedes mandar el secret en header X-TRADINGVIEW-SECRET
    if TRADINGVIEW_SECRET:
        provided = request.headers.get("X-TRADINGVIEW-SECRET")
        if provided != TRADINGVIEW_SECRET:
            return jsonify(ok=False, error="unauthorized"), 401

    # 2) Lee el JSON EXACTO que envía TradingView
    payload = request.get_json(silent=True, force=False) or {}
    app.logger.info(f"[WX] {json.dumps(payload, ensure_ascii=False)}")

    # 3) Normaliza campos sin cambiar el contenido original
    symbol = (payload.get("symbol") or "").upper().strip()
    signal_raw = (payload.get("signal") or "").strip()
    price = payload.get("price")

    # 4) Filtros simples para que SOLO pasen señales válidas a tu canal
    if symbol not in ALLOWED_SYMBOLS:
        return jsonify(ok=True, skipped="symbol_not_allowed"), 200

    label = classify_signal(signal_raw)
    if label == "UNKNOWN":
        # No publicamos si no reconocemos el tipo
        return jsonify(ok=True, skipped="signal_not_recognized"), 200

    # 5) Formatea y envía al canal
    text = format_message(symbol, signal_raw, price)
    send_to_telegram(text)

    return jsonify(ok=True), 200


if __name__ == "__main__":
    # Ejecuta el servidor
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
