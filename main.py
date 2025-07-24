from flask import Flask, request, jsonify
import requests
import os
import threading

app = Flask(__name__)

# Obtén las variables desde el entorno que te da Railway
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

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
    # Asegúrate de que las variables existen
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("ERROR: Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        return {"ok": False, "error": "Missing TELEGRAM_TOKEN or CHAT_ID"}

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": str(CHAT_ID),    # por si el chat_id es numérico, envíalo como string
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

    if isinstance(data, dict):
        side = data.get("signal", "").lower()
        price = data.get("price", 0)
        print("Campo 'price' recibido:", price, type(price))
        try:
            price = float(price)
        except Exception as e:
            print("Error al convertir price a float:", e)
            price = 0
        symbol = data.get("symbol", "???")
        if price > 0 and side in ["buy", "sell"]:
            sl = SL_BUY if side == "buy" else SL_SELL
            niveles = calcular_tps_sl(price, TPS, sl, side)
            emoji = "📈" if side == "buy" else "📉"
            msg = f"""{emoji} Nueva señal Infinity Algo ({side.upper()}) en {symbol}
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
    else:
        # Si no es JSON, es texto plano
        msg = f"Alerta TradingView (mensaje simple):\n{data}"

    threading.Thread(target=send_telegram_message, args=(msg,)).start()
    return jsonify({"status": "ok"})

@app.route("/test_telegram")
def test_telegram():
    """Ruta simple para probar que Telegram envía mensaje."""
    print("DEBUG: /test_telegram called")
    result = send_telegram_message("Mensaje de prueba desde Railway ✔️")
    return "Mensaje de prueba enviado (revisa logs y Telegram)\n" + str(result)

if __name__ == "__main__":
    app.run(port=5000, host="0.0.0.0")
