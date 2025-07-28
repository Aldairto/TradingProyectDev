# mt5_utils.py
import MetaTrader5 as mt5
import time

MAGIC = 20240725

def calcular_tps(price, tps):
    return [round(price * (1 + tp/100), 2) for tp in tps]

def cerrar_posiciones_hasta_vacio(symbol, tipo=None, max_reintentos=3):
    for intento in range(max_reintentos):
        posiciones = mt5.positions_get(symbol=symbol)
        if not posiciones or (tipo is not None and not any(p.type == tipo for p in posiciones)):
            print(f"[LOG] Todas las posiciones del tipo {tipo} para {symbol} están cerradas.")
            return True

        for pos in posiciones:
            if tipo is not None and pos.type != tipo:
                continue
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                print(f"[ERROR] No se pudo obtener tick de {symbol}.")
                continue
            close_price = tick.ask if pos.type == mt5.POSITION_TYPE_SELL else tick.bid
            order_type = mt5.ORDER_TYPE_BUY if pos.type == mt5.POSITION_TYPE_SELL else mt5.ORDER_TYPE_SELL
            close_request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": order_type,
                "position": pos.ticket,
                "price": close_price,
                "magic": MAGIC,
                "comment": f"Cierre forzado por señal opuesta",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            result = mt5.order_send(close_request)
            if result and hasattr(result, "retcode") and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"[OK] Posición cerrada (ticket {pos.ticket}) por señal opuesta.")
            else:
                print(f"[ERROR] No se pudo cerrar ticket {pos.ticket}: "
                      f"{getattr(result, 'retcode', 'SIN RESULTADO')} "
                      f"({getattr(result, 'comment', 'NO DATA')}) "
                      f"result={result}")
        time.sleep(0.5)
    # Comprobación final
    posiciones_restantes = mt5.positions_get(symbol=symbol)
    abiertas = [p for p in posiciones_restantes if tipo is None or p.type == tipo] if posiciones_restantes else []
    if abiertas:
        print(f"[CRÍTICO] No se lograron cerrar todas las posiciones tras {max_reintentos} intentos.")
        return False
    print(f"[LOG] Todas las posiciones del tipo {tipo} para {symbol} fueron cerradas (confirmado tras reintentos).")
    return True

def validar_tp_vs_stop_level(symbol, tps, tipo_orden):
    info = mt5.symbol_info(symbol)
    if not info:
        print(f"[ERROR] No se pudo obtener info de {symbol}.")
        return []
    stops_level = info.stops_level * info.point
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"[ERROR] No se pudo obtener tick de {symbol}.")
        return []
    precio_actual = tick.bid if tipo_orden == mt5.ORDER_TYPE_SELL else tick.ask
    tps_validos = []
    for i, tp in enumerate(tps):
        distancia = abs(tp - precio_actual)
        if distancia >= stops_level:
            tps_validos.append(tp)
        else:
            print(f"[ERROR] TP{i+1} ({tp}) demasiado cerca. No será usado (mínimo {stops_level:.2f}).")
    return tps_validos
