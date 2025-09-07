from flask import Flask, request, jsonify
import os, sys

app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/")
def index():
    return "ok"

@app.post("/echo")
def echo():
    raw = request.get_data(cache=False, as_text=True)
    return jsonify({"raw": raw})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"[BOOT] starting Flask on 0.0.0.0:{port} pid={os.getpid()}", flush=True)
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception:
        import traceback; traceback.print_exc()
        sys.exit(1)
