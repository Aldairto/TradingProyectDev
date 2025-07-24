from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Agregar debug
print(">>> TELEGRAM_TOKEN:", repr(TELEGRAM_TOKEN))
print(">>> TELEGRAM_CHAT_ID:", repr(TELEGRAM_CHAT_ID))

# Configuración de TP y SL (porcentaje)
TPS = [0.2, 0.5, 1, 2, 3, 5]  # TP1 a TP6 (%)
SL_BUY = 0.40
SL_SELL = 0.40

def classify_signal(signal_text):
    s = signal_text.lower()
    if "buy/compra normal o smart" in s:
        return "CONFIRMADA_BUY"
    elif "sell/venta normal o smart" in s:
        return "CONFIRMADA_SELL"
    elif "posible buy" in s:
        return "POTENCIAL_BUY"
    elif "posible sell" in s:
        return "POTENCIAL_SELL"
    else:
        return "DESCONOCIDO"

def calcular_tps_sl(price, tps, sl, side="buy"):
    niveles = {}
    price = float(price)
    if side == "buy":
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 + tp / 100), 2)
        niveles["SL"] = round(price * (1 - sl / 100), 2)
    else:
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 - tp / 100), 2)
        niveles["SL"] = round(price * (1 + sl / 100), 2)
    return niveles

def formato_tps_sl(niveles):
    iconos = ["🎯"] * 6
    tp_lines = ""
    for i in range(1, 7):
        tp_lines += f"{iconos[i-1]} <b>TP{i}:</b> {niveles.get(f'TP{i}', '-')}\n"
    tp_lines += f"🛡️ <b>SL:</b> {niveles.get('SL', '-')}\n"
    return tp_lines

def send_telegram_message(tipo, signal_raw, price, symbol, niveles=None):
    tipo_map = {
        "CONFIRMADA_BUY": "🟢 COMPRA CONFIRMADA",
        "CONFIRMADA_SELL": "🔴 VENTA CONFIRMADA",
        "POTENCIAL_BUY": "🟡 POSIBLE COMPRA",
        "POTENCIAL_SELL": "🟠 POSIBLE VENTA",
        "DESCONOCIDO": "❓ SEÑAL DESCONOCIDA"
    }
    tipo_str = tipo_map.get(tipo, tipo)
    message = (
        f"🚦 <b>Señal de TradingView</b>\n"
        f"<b>Tipo:</b> {tipo_str}\n"
        f"<b>Mensaje original:</b> {signal_raw}\n"
        f"<b>Precio:</b> <code>{price}</code>\n"
        f"<b>Símbolo:</b> <code>{symbol}</code>\n"
    )
    if niveles:
        message += "\n<b>Take Profit / Stop Loss:</b>\n"
        message += formato_tps_sl(niveles)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": int(TELEGRAM_CHAT_ID),  # fuerza a entero (si falla, prueba como str)
        "text": message,
        "parse_mode": "HTML"
    }
    print(">> Enviando a Telegram:", data)
    r = requests.post(url, data=data)
    print(">> Respuesta de Telegram:", r.text)
    return r.text

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Alerta recibida:", data)
    signal = data.get("signal", "")
    price = data.get("price", "N/A")
    symbol = data.get("symbol", "N/A")
    tipo = classify_signal(signal)
    niveles = None

    if tipo == "CONFIRMADA_BUY":
        niveles = calcular_tps_sl(price, TPS, SL_BUY, side="buy")
    elif tipo == "CONFIRMADA_SELL":
        niveles = calcular_tps_sl(price, TPS, SL_SELL, side="sell")

    send_telegram_message(tipo, signal, price, symbol, niveles)
    return jsonify({"status": "ok"})

@app.route("/test_telegram")
def test_telegram():
    # Test de envío simple, aislado
    result = send_telegram_message("CONFIRMADA_BUY", "PRUEBA TEST", 1234, "XAUUSD", None)
    return f"Enviado. Respuesta: {result}"

@app.route("/", methods=["GET"])
def root():
    return "¡Bot de Trading activo!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
