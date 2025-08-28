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
            price = mt5.symbol_info_tick(symbol).bid if pos.type == 0 else mt5.symbol_info_tick(symbol).ask
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
                print(f"[ERROR] order_send retornó None. Error: {getattr(result, 'retcode', None)} ({getattr(result, 'comment', '')})")
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
