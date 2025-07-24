from flask import Flask
import os
import requests

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot online"

@app.route("/verifica_vars")
def verifica_vars():
    # Muestra parte de las variables para evitar exponer el token completo
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return f"❌ FALTAN VARIABLES DE ENTORNO. TOKEN: {token}, CHAT_ID: {chat_id}"
    return f"✅ TOKEN: {token[:10]}... | CHAT_ID: {chat_id}"

@app.route("/test_telegram")
def test_telegram():
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return "❌ ERROR: Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID", 500
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": "🚦Prueba de envío desde Railway - ¡si ves esto, todo funciona! 🚦"
    }
    resp = requests.post(url, data=data)
    return f"Enviado, respuesta: {resp.text}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
