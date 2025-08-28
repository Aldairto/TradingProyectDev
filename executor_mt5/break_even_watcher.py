# break_even_watcher.py (Corregido y Optimizado)

import MetaTrader5 as mt5
import time

# Parámetros BreakEven
BE_PIPS_TRIGGER = 50  # Ajustado recomendado para GOLD
SYMBOLS = ["GOLD"]
MAGIC = 20240725
tolerancia_sl = 0.02  # 2 pips de tolerancia

# Parámetros TP/SL copiados desde main.py
TPS = [0.2, 0.5, 1, 2, 3, 5]  # (% del precio de entrada)
SL_BUY = 0.40
SL_SELL = 0.40

def calcular_tps_sl(price, tps, sl, side="buy"):
    niveles = {}
    if side == "buy":
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 + tp / 100), 2)
        niveles["SL"] = round(price * (1 - sl / 100), 2)
    else:
        for i, tp in enumerate(tps, 1):
            niveles[f"TP{i}"] = round(price * (1 - tp / 100), 2)
        niveles["SL"] = round(price * (1 + sl / 100), 2)
    return niveles


def mover_sl_break_even(symbol, ticket, entry_price, tp):
    sl_request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": ticket,
        "sl": entry_price,
        "tp": tp,
        "magic": MAGIC,
        "comment": "SL BE auto",
    }
    result = mt5.order_send(sl_request)
    if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"[BE] SL movido a BE para posición {ticket}")
    else:
        print(f"[BE-ERROR] Fallo mover SL a BE {ticket}: {getattr(result, 'comment', '')}")


def revisar_posiciones():
    while True:
        for symbol in SYMBOLS:
            posiciones = mt5.positions_get(symbol=symbol)
            if posiciones is None:
                continue
            for pos in posiciones:
                entry = pos.price_open
                tipo_posicion = "buy" if pos.type == mt5.POSITION_TYPE_BUY else "sell"
                niveles = calcular_tps_sl(entry, TPS, SL_BUY if tipo_posicion == "buy" else SL_SELL, side=tipo_posicion)
                tp_1 = niveles["TP1"]

                current_price = mt5.symbol_info_tick(symbol).bid if pos.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(symbol).ask

                pips_ganados = (current_price - entry) if pos.type == mt5.POSITION_TYPE_BUY else (entry - current_price)
                pips_ganados *= 100

                sl_actual = pos.sl

                if pips_ganados >= BE_PIPS_TRIGGER and abs(sl_actual - entry) > tolerancia_sl:
                    mover_sl_break_even(symbol, pos.ticket, entry, tp_1)

        time.sleep(5)


def main():
    print("[BE-WATCHER] Iniciando vigilancia de SL Break-Even...")
    if not mt5.initialize():
        print("[ERROR] No se pudo inicializar MT5 en Break-Even Watcher.")
        return
    revisar_posiciones()


if __name__ == "__main__":
    main()