# -*- coding: utf-8 -*-
import os
import sys
import time
import threading
from datetime import datetime

import requests
import MetaTrader5 as mt5

# === Dependencias del proyecto ===
sys.path.append("../backend")
from db import insertar_ejecucion, get_pending_orders, update_order_status
from mt5_utils import cerrar_posiciones_hasta_vacio, calcular_tps_porcentaje

# ================== CONFIG ==================
SYMBOL_MAP = {"XAUUSD": "GOLD"}

TPS_PERCENT = [0.2, 0.5, 1, 2, 3, 5]   # TPs en %
VOLUMES     = [0.03, 0.02, 0.01]       # lotes por parcial
SL_PERCENT  = 10.0                     # SL en %

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

USE_MT5_AUTOTRADING = os.getenv("USE_MT5_AUTOTRADING", "true").lower() == "true"

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
AUTO_MODE_FILE = os.getenv("AUTO_MODE_FILE") or os.path.join(BASE_DIR, "auto_mode.flag")
AUTO_MODE_ENV_DEFAULT = os.getenv("AUTO_MODE", "false").lower() == "true"

EXPECTED_MT5_LOGIN   = os.getenv("EXPECTED_MT5_LOGIN")
STRICT_ACCOUNT_CHECK = os.getenv("STRICT_ACCOUNT_CHECK", "true").lower() == "true"

DEFAULT_SYMBOL = SYMBOL_MAP.get("XAUUSD", "GOLD")

OFF_ALERT_INTERVAL_SEC = int(os.getenv("OFF_ALERT_INTERVAL_SEC", "900"))  # 15 min
_last_off_alert_ts = 0

_prev_auto_mode = None
# =============================================


# --------------- Utilidades ---------------
def enviar_mensaje_telegram(texto: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": texto}, timeout=8
        )
    except Exception as e:
        print(f"[ERROR] Telegram: {e}")

def notificador_activo():
    while True:
        enviar_mensaje_telegram("🤖 Activo")
        time.sleep(1800)  # 30 min

def _fmt(n):
    try:
        return f"{float(n):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    except:
        return str(n)


# --------- Lectura de AUTO_MODE ----------
def _from_mt5_auto_mode():
    try:
        term = mt5.terminal_info()
        if term is None:
            return None, "mt5", "no-terminal-info"
        val = bool(getattr(term, "trade_allowed", False))
        return val, "mt5", f"trade_allowed={val}"
    except Exception as e:
        return None, "mt5", f"error:{e}"

def _from_file_auto_mode():
    try:
        if os.path.isfile(AUTO_MODE_FILE):
            raw = open(AUTO_MODE_FILE, "r", encoding="utf-8", errors="ignore").read().strip().lower()
            if "on" in raw or raw in ("1", "true", "yes", "activo", "active"):
                return True, "file", raw
            if "off" in raw or raw in ("0", "false", "no", "inactivo"):
                return False, "file", raw
            return False, "file", raw
        return None, "file", "missing"
    except Exception as e:
        return None, "file", f"error:{e}"

def leer_auto_mode():
    if USE_MT5_AUTOTRADING:
        val, src, det = _from_mt5_auto_mode()
        if val is not None:
            return val, src, det
    val, src, det = _from_file_auto_mode()
    if val is not None:
        return val, src, det
    return AUTO_MODE_ENV_DEFAULT, "env", str(AUTO_MODE_ENV_DEFAULT)


# --------- Chequeo de símbolo ----------
def _symbol_trading_status(symbol: str):
    try:
        info = mt5.symbol_info(symbol)
        if not info or not info.visible:
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)
        if not info:
            return False, "no-symbol-info"

        ok_modes = set()
        for name in ("SYMBOL_TRADE_MODE_FULL", "SYMBOL_TRADE_MODE_LONGONLY", "SYMBOL_TRADE_MODE_SHORTONLY"):
            if hasattr(mt5, name):
                ok_modes.add(getattr(mt5, name))
        tm = getattr(info, "trade_mode", None)
        allowed = tm in ok_modes if tm is not None else True
        return allowed, f"trade_mode={tm}"
    except Exception as e:
        return False, f"error:{e}"


# --------- Mensajes ultra-cortos ----------
def _msg_off(src: str) -> str:
    if src == "mt5":
        return "⏸️ Bot en pausa (AutoTrading OFF). Actívalo en MT5 (Ctrl+E)"
    if src == "file":
        return f'⏸️ Bot en pausa (flag OFF). Escribe "on" en auto_mode.flag'
    return "⏸️ Bot en pausa (config OFF). AUTO_MODE=true"

def _msg_on() -> str:
    return "✅ AutoTrading ON — ejecutando"


def _recordatorio_off_si_corresponde(src: str):
    global _last_off_alert_ts
    now = time.time()
    if now - _last_off_alert_ts >= OFF_ALERT_INTERVAL_SEC:
        enviar_mensaje_telegram(_msg_off(src))
        _last_off_alert_ts = now


# --------- Helpers de tipos ----------
def _es_alerta_informativa(t_upper: str) -> bool:
    """'POSIBLE BUY/SELL' y 'TAKE PROFIT *' no ejecutan órdenes."""
    if "POSIBLE BUY" in t_upper or "POSIBLE SELL" in t_upper:
        return True
    if "TAKE PROFIT" in t_upper:
        return True
    return False


# --------------- Startup checks ---------------
def startup_checks() -> bool:
    term = mt5.terminal_info()
    acc  = mt5.account_info()
    if term is None or acc is None:
        enviar_mensaje_telegram("❌ MT5 sin info de terminal/cuenta")
        return False

    auto_mode, src, det = leer_auto_mode()
    sym_ok, sym_det = _symbol_trading_status(DEFAULT_SYMBOL)

    resumen_corto = (
        f"🧪 Acc:{acc.login} | Bal:{_fmt(acc.balance)} | Eq:{_fmt(acc.equity)} | "
        f"Auto:{'ON' if auto_mode else 'OFF'} ({src})"
    )
    print(resumen_corto)
    enviar_mensaje_telegram(resumen_corto)

    if EXPECTED_MT5_LOGIN:
        ok_login = str(acc.login) == str(EXPECTED_MT5_LOGIN)
        if not ok_login and STRICT_ACCOUNT_CHECK:
            enviar_mensaje_telegram("❌ Cuenta no coincide. Abortando.")
            return False

    if not sym_ok:
        print(f"[WARN] Símbolo {DEFAULT_SYMBOL} restringido ({sym_det})")

    enviar_mensaje_telegram(_msg_on() if auto_mode else _msg_off(src))
    return True


# --------------- Ejecución de órdenes ---------------
def ejecutar_orden(order: dict) -> bool:
    symbol     = order["symbol"]
    symbol_mt5 = SYMBOL_MAP.get(symbol, symbol)
    order_type = order["order_type"]
    price      = float(order["price"])
    side       = "buy" if "buy" in order_type.lower() else "sell"

    tps, sl = calcular_tps_porcentaje(price, TPS_PERCENT, SL_PERCENT, side=side)
    tipo_mt5 = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL

    side_map = {
        "BUY/COMPRA NORMAL O SMART": "buy",
        "POSIBLE BUY": "buy",
        "SELL/VENTA NORMAL O SMART": "sell",
        "POSIBLE SELL": "sell",
        # nuevos tipos informativos
        "TAKE PROFIT BUY": "buy",
        "TAKE PROFIT LONG": "buy",
        "TAKE PROFIT SELL": "sell",
        "TAKE PROFIT SHORT": "sell",
        "buy": "buy", "sell": "sell"
    }
    side_db = side_map.get(order_type.upper(), order_type if order_type in ["buy", "sell"] else "buy")

    opposite_type = mt5.POSITION_TYPE_SELL if side == "buy" else mt5.POSITION_TYPE_BUY
    print(f"[LOG] Cerrando posiciones {'SELL' if opposite_type==1 else 'BUY'} antes de abrir {order_type.upper()}...")
    if not cerrar_posiciones_hasta_vacio(symbol_mt5, tipo=opposite_type):
        print("[CRÍTICO] No se lograron cerrar todas las posiciones.")
        return False

    success = False
    for i, (tp, volume) in enumerate(zip(tps, VOLUMES), 1):
        tick = mt5.symbol_info_tick(symbol_mt5)
        if not tick:
            print("[ERROR] Sin tick de símbolo.")
            continue

        price_exec = tick.ask if side == "buy" else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol_mt5,
            "volume": volume,
            "type": tipo_mt5,
            "price": price_exec,
            "sl": sl,
            "tp": tp,
            "deviation": 10,
            "magic": 20240725,
            "comment": f"TP{i}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC
        }

        result = mt5.order_send(request)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"[OK] Parcial {i} ejecutada. Ticket: {result.order}")
            insertar_ejecucion(order.get("id"), result.order, symbol, side_db,
                               volume, request["price"], tp, sl, now_str)
            success = True
        else:
            print(f"[ERROR] Parcial {i} no ejecutada: {getattr(result, 'retcode', 'No result')} result={result}")

    if not success:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        insertar_ejecucion(order.get("id"), None, symbol, side_db,
                           sum(VOLUMES), price, None, sl, now_str)
    else:
        update_order_status(order.get("id"), "executed")

    return success


# ---------------------- MAIN ----------------------
def main():
    global _prev_auto_mode, _last_off_alert_ts

    print("[LOG] Iniciando MT5 Executor...")
    if not mt5.initialize():
        enviar_mensaje_telegram("❌ No se pudo iniciar MT5")
        return

    acc = mt5.account_info()
    print(f"[MTS] Conectado como {acc.login if acc else 'N/A'}. Balance: {acc.balance if acc else 'N/A'}.")

    if not startup_checks():
        print("[CRÍTICO] Startup checks fallaron. Saliendo.")
        return

    threading.Thread(target=notificador_activo, daemon=True).start()

    print("[LOG] Loop principal...")
    while True:
        auto_mode, src, det = leer_auto_mode()

        if _prev_auto_mode is None or _prev_auto_mode != auto_mode:
            _prev_auto_mode = auto_mode
            if auto_mode:
                enviar_mensaje_telegram(_msg_on())
                print(f"[MODO] ON  [src={src} det={det}]")
            else:
                enviar_mensaje_telegram(_msg_off(src))
                _last_off_alert_ts = time.time()
                print(f"[MODO] OFF [src={src} det={det}]")

        if not auto_mode:
            _recordatorio_off_si_corresponde(src)
            time.sleep(5)
            continue

        orders = get_pending_orders()
        print(f"[LOG] Órdenes pendientes: {len(orders)}")
        for order in orders:
            t_upper = str(order["order_type"]).upper()

            # --- NUEVO: manejar alertas informativas de TP y "Posible" ---
            if _es_alerta_informativa(t_upper):
                update_order_status(order.get("id"), "take_profit" if "TAKE PROFIT" in t_upper else "informativa")
                enviar_mensaje_telegram(
                    f"🎯 {t_upper} | {order.get('symbol')} @ {order.get('price')}"
                )
                print(f"[INFO] Alerta informativa detectada, no se ejecuta: {t_upper}")
                continue
            # -------------------------------------------------------------

            ejecutar_orden(order)

        time.sleep(5)


if __name__ == "__main__":
    main()
