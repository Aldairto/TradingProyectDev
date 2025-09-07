# -*- coding: utf-8 -*-
import os
import time
import threading
import re
from datetime import datetime
from typing import Optional

import requests
import MetaTrader5 as mt5

# === Dependencias del proyecto (db en mismo folder) ===
from db import insertar_ejecucion, get_pending_orders, update_order_status
from mt5_utils import (
    cerrar_posiciones_hasta_vacio,
    calcular_tps_porcentaje,
    mover_sl_en_take_profit_inmediato,  # Mueve SL de inmediato según TP recibido
)

# =====================================================================
# ===============            CONFIG RÁPIDA            ==================
# =====================================================================
# Controlas ON/OFF, TPs, lotes, SL y si permite movimientos de seguridad por símbolo.
# *** SIMPLE PARA ÓRDENES MÚLTIPLES ***
#   La 1ª orden usa *_1
#   Las siguientes (2ª, 3ª, …) usan *_OTROS
SYMBOLS = {
    "XAUUSD": {
        "mt5": "GOLD",
        "enabled": True,
        "allow_safety_updates_when_off": True,
        # Entrada Principal
        "tps_percent_1":    [0.2, 0.5, 1, 2, 3, 5],
        "volumes_1":        [0.01, 0.01, 0.01],
        # Entradas siguientes
        "tps_percent_OTROS":[0.2, 0.5, 1, 2, 3, 5],
        "volumes_OTROS":    [0.01, 0.01],
        "sl_percent": 10.0,
    },
    "BTCUSD": {
        "mt5": "BTCUSD",
        "enabled": True,
        "allow_safety_updates_when_off": True,
        # Entrada Principal
        "tps_percent_1":    [0.2, 0.5, 1, 2, 3, 5],
        "volumes_1":        [0.01, 0.01, 0.01],
        # Segundas entradas
        "tps_percent_OTROS":[0.2, 0.5, 1.2, 2.5, 3.5, 5.5],
        "volumes_OTROS":    [0.01, 0.01],
        "sl_percent": 12.0,
    },
}

# ================== CONFIG GLOBAL (no tocar usualmente) ==================
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # usa el mismo chat que ya notificas

USE_MT5_AUTOTRADING = os.getenv("USE_MT5_AUTOTRADING", "true").lower() == "true"

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
AUTO_MODE_FILE = os.getenv("AUTO_MODE_FILE") or os.path.join(BASE_DIR, "auto_mode.flag")
AUTO_MODE_ENV_DEFAULT = os.getenv("AUTO_MODE", "false").lower() == "true"

EXPECTED_MT5_LOGIN   = os.getenv("EXPECTED_MT5_LOGIN")
STRICT_ACCOUNT_CHECK = os.getenv("STRICT_ACCOUNT_CHECK", "true").lower() == "true"

# DEFAULT_SYMBOL para checks de arranque
DEFAULT_SYMBOL_RAW = next(iter(SYMBOLS.keys())) if SYMBOLS else "XAUUSD"
DEFAULT_SYMBOL_MT5 = SYMBOLS.get(DEFAULT_SYMBOL_RAW, {}).get("mt5", DEFAULT_SYMBOL_RAW)

OFF_ALERT_INTERVAL_SEC = int(os.getenv("OFF_ALERT_INTERVAL_SEC", "900"))  # 15 min
_last_off_alert_ts = 0
_prev_auto_mode = None

# Override manual desde Telegram (/pause, /resume)
_manual_override: Optional[bool] = None  # None = sin override, True=ON, False=OFF

# Guarda el login de la cuenta MT5 que está ejecutando este bot
ACCOUNT_LOGIN: Optional[str] = None
# ========================================================================


# ---------------- Helper de acceso a config por símbolo -----------------
def get_symbol_cfg(symbol_raw: str):
    """
    Devuelve (cfg, symbol_mt5, enabled) para symbol_raw (ej: 'XAUUSD').
    Si no existe en SYMBOLS, crea uno por defecto 'passthrough'.
    """
    base = SYMBOLS.get(symbol_raw)
    if base:
        return base, base.get("mt5", symbol_raw), bool(base.get("enabled", True))
    # Fallback si llega un símbolo no configurado:
    cfg = {
        "mt5": symbol_raw,
        "enabled": True,
        "allow_safety_updates_when_off": False,
        "tps_percent_1":    [0.2, 0.5, 1, 2, 3, 5],
        "volumes_1":        [0.01, 0.02, 0.03],
        "tps_percent_OTROS":[0.2, 0.5, 1, 2, 3, 5],
        "volumes_OTROS":    [0.01, 0.02, 0.03],
        "sl_percent": 10.0,
    }
    return cfg, symbol_raw, True


# --------- Resolver set según índice de orden (1ª vs OTROS) -------------
def _get_sets(cfg: dict, order_idx: int):
    """
    order_idx=1 => usa *_1; order_idx>=2 => usa *_OTROS
    Con fallback si faltara alguna clave (no se rompe).
    """
    tps_1 = cfg.get("tps_percent_1") or cfg.get("tps_percent") or [0.2, 0.5, 1, 2, 3, 5]
    vol_1 = cfg.get("volumes_1")     or cfg.get("volumes")     or [0.01, 0.02, 0.03]

    tps_otros = cfg.get("tps_percent_OTROS") or tps_1
    vol_otros = cfg.get("volumes_OTROS")     or vol_1

    if order_idx <= 1:
        return tps_1, vol_1
    return tps_otros, vol_otros


# --------------- Utilidades ---------------
def enviar_mensaje_telegram(texto: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": texto},
            timeout=8,
        )
    except Exception as e:
        print(f"[ERROR] Telegram: {e}")

def notificador_activo():
    while True:
        enviar_mensaje_telegram("Actv Desarrollo")
        time.sleep(1800)  # 30 min

def _fmt(n):
    try:
        return f"{float(n):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    except:
        return str(n)


# --------- Lectura/escritura de AUTO_MODE ----------
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

def _write_auto_mode_file(on: bool) -> bool:
    try:
        with open(AUTO_MODE_FILE, "w", encoding="utf-8") as f:
            f.write("on" if on else "off")
        return True
    except Exception as e:
        print(f"[FILE] Error al escribir auto_mode.flag: {e}")
        return False

def leer_auto_mode():
    # 0) Override manual desde Telegram
    global _manual_override
    if _manual_override is not None:
        return _manual_override, "manual", "telegram"

    # 1) Info de MT5 si así se configuró
    if USE_MT5_AUTOTRADING:
        val, src, det = _from_mt5_auto_mode()
        if val is not None:
            return val, src, det

    # 2) Flag en archivo
    val, src, det = _from_file_auto_mode()
    if val is not None:
        return val, src, det

    # 3) Valor por ENV como fallback
    return AUTO_MODE_ENV_DEFAULT, "env", str(AUTO_MODE_ENV_DEFAULT)


# --------- Chequeo de símbolo en MT5 ----------
def _symbol_trading_status(symbol_mt5: str):
    try:
        info = mt5.symbol_info(symbol_mt5)
        if not info or not info.visible:
            mt5.symbol_select(symbol_mt5, True)
            info = mt5.symbol_info(symbol_mt5)
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
    if src == "manual":
        return "⏸️ Bot en pausa (Telegram /pause)"
    return "⏸️ Bot en pausa (config OFF). AUTO_MODE=true"

def _msg_on() -> str:
    return "✅ AutoTrading ON — ejecutando"

def _recordatorio_off_si_corresponde(src: str):
    global _last_off_alert_ts
    now = time.time()
    if now - _last_off_alert_ts >= OFF_ALERT_INTERVAL_SEC:
        enviar_mensaje_telegram(_msg_off(src))
        _last_off_alert_ts = now


# ============== Resumen de símbolos al iniciar ===================
def _symbols_status_summary() -> str:
    if not SYMBOLS:
        return "Sin símbolos configurados."
    parts = []
    for raw, cfg in SYMBOLS.items():
        mt5_name = cfg.get("mt5", raw)
        on = "ON" if cfg.get("enabled", True) else "OFF"
        seg = " [seg]" if cfg.get("allow_safety_updates_when_off", False) else ""
        parts.append(f"{raw} ({mt5_name})={on}{seg}")
    return " | ".join(parts)


# ======= Helpers cierre posiciones para comandos Telegram =======
def _cerrar_todo() -> int:
    """Cierra todas las posiciones de todos los símbolos. Devuelve cuántas cerró (aprox)."""
    before = len(mt5.positions_get() or [])
    posiciones = mt5.positions_get() or []
    symbols = sorted({p.symbol for p in posiciones})
    for s in symbols:
        cerrar_posiciones_hasta_vacio(s, tipo=None)
    after = len(mt5.positions_get() or [])
    cerradas = max(0, before - after)
    return cerradas

def _cerrar_por_simbolo(symbol_mt5: str, side: Optional[str]) -> int:
    """Cierra por símbolo y opcionalmente por lado ('buy'/'sell'). Devuelve cuántas cerró (aprox)."""
    side_map = {"buy": mt5.POSITION_TYPE_BUY, "sell": mt5.POSITION_TYPE_SELL}
    tipo = side_map.get((side or "").lower(), None)
    before = len([p for p in (mt5.positions_get() or []) if p.symbol == symbol_mt5 and (tipo is None or p.type == tipo)])
    cerrar_posiciones_hasta_vacio(symbol_mt5, tipo=tipo)
    after = len([p for p in (mt5.positions_get() or []) if p.symbol == symbol_mt5 and (tipo is None or p.type == tipo)])
    return max(0, before - after)


# ================== Listener de comandos Telegram ==================
def _telegram_authorized(chat_id) -> bool:
    if not TELEGRAM_CHAT_ID:
        return True  # si no está seteado, no filtramos (útil para pruebas)
    try:
        return str(chat_id) == str(TELEGRAM_CHAT_ID)
    except:
        return False

def _tg_send(text: str):
    enviar_mensaje_telegram(text)

def _parse_cmd(text: str):
    """
    /closeall | /panic
    /close <SYMBOL>
    /close <SYMBOL> buy|sell
    /positions
    /pause
    /resume
    /status
    /help
    """
    text = (text or "").strip()
    if re.match(r"^/(closeall|panic)\b", text, flags=re.I):
        return {"cmd": "closeall"}
    m = re.match(r"^/close\s+([A-Za-z0-9\._-]+)(?:\s+(buy|sell))?\s*$", text, flags=re.I)
    if m:
        return {"cmd": "close", "symbol": m.group(1), "side": (m.group(2) or "").lower() or None}
    if re.match(r"^/positions\b", text, flags=re.I):
        return {"cmd": "positions"}
    if re.match(r"^/pause\b", text, flags=re.I):
        return {"cmd": "pause"}
    if re.match(r"^/resume\b", text, flags=re.I):
        return {"cmd": "resume"}
    if re.match(r"^/status\b", text, flags=re.I):
        return {"cmd": "status"}
    if re.match(r"^/help\b", text, flags=re.I):
        return {"cmd": "help"}
    return None

def _positions_summary() -> str:
    pos = mt5.positions_get() or []
    if not pos:
        return "Sin posiciones abiertas."
    # resumen por símbolo y side
    agg = {}
    for p in pos:
        side = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        key = (p.symbol, side)
        agg.setdefault(key, 0.0)
        agg[key] += float(p.volume)
    parts = [f"{sym} {side}: {vol}" for (sym, side), vol in agg.items()]
    return " | ".join(parts)

def _telegram_listener_loop():
    global _manual_override  # declarar al inicio de la función

    if not TELEGRAM_TOKEN:
        print("[TG] TELEGRAM_TOKEN no definido; listener desactivado.")
        return
    print("[TG] Listener de Telegram iniciado. Comandos: /closeall, /close <SYMBOL> [buy|sell], /positions, /pause, /resume, /status, /help")
    last_update_id = None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    while True:
        try:
            params = {"timeout": 25}
            if last_update_id is not None:
                params["offset"] = last_update_id + 1
            r = requests.get(url, params=params, timeout=35)
            data = r.json()
            if not data.get("ok"):
                time.sleep(2)
                continue
            for upd in data.get("result", []):
                last_update_id = upd.get("update_id", last_update_id)
                msg = upd.get("message") or upd.get("edited_message")
                if not msg or "text" not in msg:
                    continue
                chat_id = msg.get("chat", {}).get("id")
                if not _telegram_authorized(chat_id):
                    continue
                text = msg.get("text", "")
                parsed = _parse_cmd(text)
                if not parsed:
                    continue

                cmd = parsed["cmd"]
                if cmd == "help":
                    _tg_send("Comandos:\n/closeall – cerrar TODO\n/close <SIMBOLO> [buy|sell]\n/positions – resumen\n/pause – pausar bot\n/resume – reanudar bot\n/status – estado actual\n")
                elif cmd == "positions":
                    _tg_send(_positions_summary())
                elif cmd == "closeall":
                    cerradas = _cerrar_todo()
                    _tg_send(f"🔒 Cerradas {cerradas} posiciones (todas).")
                elif cmd == "close":
                    sym_raw = parsed["symbol"]
                    cfg, symbol_mt5, _ = get_symbol_cfg(sym_raw if sym_raw in SYMBOLS else sym_raw)
                    cerradas = _cerrar_por_simbolo(symbol_mt5, parsed.get("side"))
                    side_txt = f" {parsed.get('side').upper()}" if parsed.get("side") else ""
                    _tg_send(f"🔒 {symbol_mt5}{side_txt}: cerradas {cerradas} posiciones.")
                elif cmd == "pause":
                    _manual_override = False
                    _write_auto_mode_file(False)
                    _tg_send("⏸️ Pausado por Telegram (/pause).")
                elif cmd == "resume":
                    _manual_override = True
                    _write_auto_mode_file(True)
                    _tg_send("▶️ Reanudado por Telegram (/resume).")
                elif cmd == "status":
                    val, src, det = leer_auto_mode()
                    _tg_send(f"Estado: {'ON' if val else 'OFF'} (src={src}; det={det})")
        except Exception as e:
            print(f"[TG] Error listener: {e}")
            time.sleep(3)

def start_telegram_listener():
    t = threading.Thread(target=_telegram_listener_loop, daemon=True)
    t.start()
# =======================================================================


# --------------- Startup checks ---------------
def startup_checks() -> bool:
    term = mt5.terminal_info()
    acc  = mt5.account_info()
    if term is None or acc is None:
        enviar_mensaje_telegram("❌ MT5 sin info de terminal/cuenta")
        return False

    auto_mode, src, det = leer_auto_mode()
    sym_ok, sym_det = _symbol_trading_status(DEFAULT_SYMBOL_MT5)

    resumen_corto = (
        f"🧪 Acc:{acc.login} | Bal:{_fmt(acc.balance)} | Eq:{_fmt(acc.equity)} | "
        f"Auto:{'ON' if auto_mode else 'OFF'} ({src})"
    )
    print(resumen_corto)
    enviar_mensaje_telegram(resumen_corto)

    # Estatus de símbolos al iniciar
    symbols_line = _symbols_status_summary()
    print(f"📋 Símbolos: {symbols_line}")
    enviar_mensaje_telegram(f"📋 Símbolos: {symbols_line}")

    if EXPECTED_MT5_LOGIN:
        ok_login = str(acc.login) == str(EXPECTED_MT5_LOGIN)
        if not ok_login and STRICT_ACCOUNT_CHECK:
            enviar_mensaje_telegram("❌ Cuenta no coincide. Abortando.")
            return False

    if not sym_ok:
        print(f"[WARN] Símbolo {DEFAULT_SYMBOL_MT5} restringido ({sym_det})")

    enviar_mensaje_telegram(_msg_on() if auto_mode else _msg_off(src))
    return True


# --------------- Ejecución de órdenes ---------------
def ejecutar_orden(order: dict, account_login: str) -> bool:
    # Config por símbolo
    symbol_raw = order["symbol"]
    cfg, symbol_mt5, _enabled = get_symbol_cfg(symbol_raw)

    order_type = order["order_type"]
    price      = float(order["price"])
    side       = "buy" if "buy" in order_type.lower() else "sell"
    tipo_mt5   = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL

    side_map = {
        "BUY/COMPRA NORMAL O SMART": "buy",
        "POSIBLE BUY": "buy",
        "SELL/VENTA NORMAL O SMART": "sell",
        "POSIBLE SELL": "sell",
        "TAKE PROFIT BUY": "buy",
        "TAKE PROFIT LONG": "buy",
        "TAKE PROFIT SELL": "sell",
        "TAKE PROFIT SHORT": "sell",
        "buy": "buy", "sell": "sell"
    }
    side_db = side_map.get(order_type.upper(), order_type if order_type in ["buy", "sell"] else "buy")

    # 1) Cierra posiciones del lado opuesto ANTES de contar las del mismo lado
    opposite_type = mt5.POSITION_TYPE_SELL if side == "buy" else mt5.POSITION_TYPE_BUY
    print(f"[LOG] Cerrando posiciones {'SELL' if opposite_type==1 else 'BUY'} antes de abrir {order_type.upper()}...")
    if not cerrar_posiciones_hasta_vacio(symbol_mt5, tipo=opposite_type):
        print("[CRÍTICO] No se lograron cerrar todas las posiciones.")
        return False

    # 2) Contar posiciones del MISMO lado para decidir 1ª vs OTROS
    pos_all = mt5.positions_get(symbol=symbol_mt5) or []
    side_code = mt5.POSITION_TYPE_BUY if side == "buy" else mt5.POSITION_TYPE_SELL
    existing_same_side = sum(1 for p in pos_all if p.type == side_code)
    order_idx = existing_same_side + 1

    # 3) Elegir sets (1ª u OTROS)
    tps_percent, volumes = _get_sets(cfg, order_idx)
    sl_percent  = float(cfg.get("sl_percent", 10.0))

    # 4) Calcular niveles TP/SL con el set elegido
    tps, sl = calcular_tps_porcentaje(price, tps_percent, sl_percent, side=side)

    success = False
    for i, (tp, volume) in enumerate(zip(tps, volumes), 1):
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
            "comment": f"TP{i}-{'1' if order_idx==1 else 'OTROS'}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC
        }

        result = mt5.order_send(request)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"[OK] Parcial {i} ({'1' if order_idx==1 else 'OTROS'}) ejecutada. Ticket: {result.order}")
            insertar_ejecucion(order.get("id"), result.order, symbol_raw, side_db,
                               volume, request["price"], tp, sl, now_str)
            success = True
        else:
            print(f"[ERROR] Parcial {i} ({'1' if order_idx==1 else 'OTROS'}) no ejecutada: {getattr(result, 'retcode', 'No result')} result={result}")

    if not success:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        insertar_ejecucion(order.get("id"), None, symbol_raw, side_db,
                           sum(volumes), price, None, sl, now_str)
    else:
        # ⬅️ Estado por CUENTA
        update_order_status(order.get("id"), account_login, "executed")

    return success


# ---------------------- MAIN ----------------------
def main():
    global _prev_auto_mode, _last_off_alert_ts, ACCOUNT_LOGIN

    print("[LOG] Iniciando MT5 Executor...")
    if not mt5.initialize():
        enviar_mensaje_telegram("❌ No se pudo iniciar MT5")
        return

    acc = mt5.account_info()
    ACCOUNT_LOGIN = str(acc.login) if acc else "unknown"
    print(f"[MTS] Conectado como {ACCOUNT_LOGIN}. Balance: {acc.balance if acc else 'N/A'}.")

    if not startup_checks():
        print("[CRÍTICO] Startup checks fallaron. Saliendo.")
        return

    # Hilo de keepalive
    threading.Thread(target=notificador_activo, daemon=True).start()

    # Hilo listener de Telegram (comandos /closeall, /pause, etc.)
    start_telegram_listener()

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

        # ⬇️ AHORA: pendientes SOLO de esta cuenta
        orders = get_pending_orders(ACCOUNT_LOGIN)
        print(f"[LOG] Órdenes pendientes para {ACCOUNT_LOGIN}: {len(orders)}")
        for order in orders:
            symbol_raw = order.get("symbol", "")
            cfg, symbol_mt5, enabled = get_symbol_cfg(symbol_raw)
            t_upper = str(order.get("order_type", "")).upper()

            # ---------- GATE POR SÍMBOLO (ON/OFF desde CONFIG) ----------
            if not enabled:
                allow_safety = bool(cfg.get("allow_safety_updates_when_off", False))
                if ("TAKE PROFIT" in t_upper) and allow_safety:
                    # Permitimos solo acciones de seguridad (mover SL/BE en TP)
                    print(f"[TOGGLE] {symbol_raw}=OFF pero se permite seguridad (TP/SL).")
                else:
                    update_order_status(order.get("id"), ACCOUNT_LOGIN, "symbol_off")
                    enviar_mensaje_telegram(f"⏸️ {symbol_raw} OFF — señal ignorada")
                    continue
            # ------------------------------------------------------------

            # 1) "Posible ..." = informativas
            if "POSIBLE BUY" in t_upper or "POSIBLE SELL" in t_upper:
                update_order_status(order.get("id"), ACCOUNT_LOGIN, "informativa")
                print(f"[INFO] Aviso detectado, no se ejecuta: {t_upper}")
                continue

            # 2) TAKE PROFIT inmediato: mover SL según TP alcanzado
            if "TAKE PROFIT" in t_upper:
                side = "buy" if ("BUY" in t_upper or "LONG" in t_upper) else "sell"
                m = re.search(r'(?:TAKE\s*PROFIT|TP)\s*(\d+)', t_upper)
                tp_index = int(m.group(1)) if m else 1
                try:
                    base_tps = (cfg.get("tps_percent_1")
                                or cfg.get("tps_percent_OTROS")
                                or [0.2, 0.5, 1, 2, 3, 5])
                    moved, npos = mover_sl_en_take_profit_inmediato(symbol_mt5, side, base_tps, tp_index=tp_index)
                    update_order_status(order.get("id"), ACCOUNT_LOGIN, "take_profit")
                    if moved:
                        enviar_mensaje_telegram(f"🎯 TAKE PROFIT {side.upper()} TP{tp_index} ⇒ SL actualizado ({symbol_raw})")
                    else:
                        enviar_mensaje_telegram(f"ℹ️ TAKE PROFIT {side.upper()} TP{tp_index} ⇒ SL ya estaba protegido ({symbol_raw})")
                except Exception as e:
                    print("[TP-IMMED] Error:", e)
                continue

            # 3) Señal ejecutable normal
            ejecutar_orden(order, ACCOUNT_LOGIN)

        time.sleep(5)


if __name__ == "__main__":
    main()
