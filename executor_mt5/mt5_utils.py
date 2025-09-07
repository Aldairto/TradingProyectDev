import MetaTrader5 as mt5
import time

def calcular_tps(price, tps, side="buy", modo="pips", invertir=False):
    price = float(price)
    levels = []
    if modo == "pips":
        for tp in tps:
            if (side == 'buy' and not invertir) or (side == 'sell' and invertir):
                levels.append(round(price + tp, 2))
            else:
                levels.append(round(price - tp, 2))
        return levels
    else:
        if side == "buy":
            for tp in tps:
                levels.append(round(price + (price * tp / 100), 2))
        else:
            for tp in tps:
                levels.append(round(price - (price * tp / 100), 2))
    return levels

def cerrar_posiciones_hasta_vacio(symbol, tipo=None, max_reintentos=3):
    for intento in range(1, max_reintentos + 1):
        print(f"[LOG] Intento {intento}: Cerrando posiciones...")
        posiciones = mt5.positions_get(symbol=symbol)
        if posiciones is None:
            print("[ERROR] No se pudieron obtener posiciones de MT5.")
            return False
        cerradas = True
        for pos in posiciones:
            print(f"[DEBUG-TIPO] ticket={pos.ticket}, symbol={pos.symbol}, type={pos.type}, volume={pos.volume}")
            if tipo is not None and pos.type != tipo:
                continue
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                print("[ERROR] Sin tick de símbolo para cerrar.")
                return False
            price = tick.bid if pos.type == 0 else tick.ask
            close_request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": 1 if pos.type == 0 else 0,
                "position": pos.ticket,
                "price": price,
                "deviation": 20,
                "magic": 20240725,
                "comment": "AutoClose",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            print(f"[DEBUG] close_request: {close_request}")
            result = mt5.order_send(close_request)
            print(f"[DEBUG] close result: {result}")
            if result is None or result.retcode not in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED, mt5.TRADE_RETCODE_DONE_PARTIAL]:
                cerradas = False
                print(f"[ERROR] order_send al cerrar. retcode={getattr(result,'retcode',None)} ({getattr(result,'comment','')})")
        if cerradas:
            print("[LOG] Todas las posiciones del tipo", tipo, "para", symbol, "están cerradas.")
            return True
        time.sleep(2)
    print("[CRÍTICO] No se lograron cerrar todas las posiciones tras reintentos.")
    return False

def calcular_tps_porcentaje(price, tps_percent, sl_percent, side="buy"):
    """
    Calcula niveles de TP y SL basados en porcentaje desde el precio.
    """
    niveles = []
    price = float(price)
    if side == "buy":
        niveles = [round(price * (1 + tp / 100), 2) for tp in tps_percent]
        sl = round(price * (1 - sl_percent / 100), 2)
    else:
        niveles = [round(price * (1 - tp / 100), 2) for tp in tps_percent]
        sl = round(price * (1 + sl_percent / 100), 2)
    return niveles, sl


# ===================== SL/TP helpers =====================

def _modify_position_sl(position_ticket, symbol, new_sl, keep_tp):
    """Modifica solo el SL de una posición con TRADE_ACTION_SLTP."""
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": int(position_ticket),
        "symbol": symbol,
        "sl": float(new_sl),
        "tp": float(keep_tp) if keep_tp else 0.0,
    }
    result = mt5.order_send(req)
    ok = (result is not None) and (result.retcode in (
        mt5.TRADE_RETCODE_DONE,
        mt5.TRADE_RETCODE_PLACED,
        mt5.TRADE_RETCODE_DONE_PARTIAL
    ))
    print(f"[SL-UPDATE] pos={position_ticket} sl->{new_sl} ok={ok} ret={getattr(result,'retcode',None)}")
    return ok


def mover_sl_en_take_profit_inmediato(symbol, side, tps_percent, tp_index=1):
    """
    Mueve el SL *inmediatamente* al recibir la alerta de TAKE PROFIT (sin validar precio actual).
    Reglas:
      - tp_index <= 1 => SL = precio de entrada (break-even)
      - tp_index >= 2 => SL = TP(tp_index-1) calculado desde la entrada de cada posición

    Devuelve:
        (did_update, num_positions)
    """
    side = (side or "").lower()
    if side not in ("buy", "sell"):
        return (False, 0)

    pos_all = mt5.positions_get(symbol=symbol) or []
    if not pos_all:
        print("[TP-IMMED] Sin posiciones para", symbol)
        return (False, 0)

    side_code = mt5.POSITION_TYPE_BUY if side == "buy" else mt5.POSITION_TYPE_SELL
    pos_side = [p for p in pos_all if p.type == side_code]
    if not pos_side:
        print(f"[TP-IMMED] No hay posiciones {side.upper()} para", symbol)
        return (False, 0)

    did = False
    for p in pos_side:
        entry = float(p.price_open)
        levels, _ = calcular_tps_porcentaje(entry, tps_percent, 0.0, side=side)

        if tp_index <= 1:
            target = entry
        else:
            idx = max(1, tp_index - 1) - 1  # 0-based del TP previo
            idx = min(idx, len(levels) - 1)
            target = levels[idx]

        current_sl = float(getattr(p, "sl", 0.0) or 0.0)
        # Solo mejorar SL (sube en BUY, baja en SELL)
        should_update = (side == "buy" and (current_sl < target or current_sl == 0.0)) or \
                        (side == "sell" and (current_sl > target or current_sl == 0.0))

        if should_update:
            ok = _modify_position_sl(p.ticket, p.symbol, target, getattr(p, "tp", 0.0))
            did = did or ok
        else:
            print(f"[TP-IMMED] SL ya ≥ objetivo (pos {p.ticket}, sl={current_sl}, objetivo={target})")

    return (did, len(pos_side))
