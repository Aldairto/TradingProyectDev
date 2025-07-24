from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

# Cargar variables de entorno de forma segura
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# DEBUG: Verifica si las variables llegan
print("DEBUG >>> TELEGRAM_TOKEN vacío:", not bool(TELEGRAM_TOKEN))
print("DEBUG >>> TELEGRAM_CHAT_ID vacío:", not bool(TELEGRAM_CHAT_ID))

# Configuración de TP y SL (porcentaje)
TPS = [0.2, 0.5, 1, 2, 3, 5]  # TP1 a TP6 (%)
SL_BUY = 0.40                  # SL para BUY (%)
SL_SELL = 0.40                 # SL para SELL (%)

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
    try:
        price = float(price)
    except Exception:
        return niveles
    if side == "buy":
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 + tp / 100), 2)
        niveles["SL"] = round(price * (1 - sl / 100), 2)
    else:  # sell
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 - tp / 100), 2)
        niveles["SL"] = round(price * (1 + sl / 100), 2)
    return niveles

def formato_tps_sl(niveles):
    iconos = ["🎯", "🎯", "🎯", "🎯", "🎯", "🎯"]
    tp_lines = ""
    for i in range(1, 7):
        tp_lines += f"{iconos[i-1]} <b>TP{i}:</b> {niveles.get(f'TP{i}', '-')}\n"
    tp_lines += f"🛡️ <b>SL:</b> {niveles.get('SL', '-')}\n"
    return tp_lines

def send_telegram_message(tipo, signal_raw, price, symbol, niveles=None):
    # Validar que las variables están presentes
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        return

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
        "chat_id": str(TELEGRAM_CHAT_ID),  # Asegura que sea str
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, data=data)
        print("Respuesta de Telegram:", r.text)
    except Exception as e:
        print("ERROR enviando a Telegram:", e)

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

@app.route("/", methods=["GET"])
def root():
    return "¡Bot de Trading activo!"

# Endpoint para probar si se pueden enviar mensajes
@app.route("/test_telegram", methods=["GET"])
def test_telegram():
    print("DEBUG: /test_telegram called")
    send_telegram_message("CONFIRMADA_BUY", "PRUEBA TEST", 1234, "XAUUSD", None)
    return "Mensaje de prueba enviado (revisa logs y Telegram)"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
