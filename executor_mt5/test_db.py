import MetaTrader5 as mt5

TICKET = 277821739  # Cambia por uno abierto
symbol = "GOLD"     # Cambia si tu símbolo es otro exactamente

if not mt5.initialize():
    print("No se pudo conectar a MT5")
    exit()

positions = mt5.positions_get(ticket=TICKET)
if not positions:
    print(f"No hay posición abierta con el ticket {TICKET}")
    mt5.shutdown()
    exit()

pos = positions[0]
volume = pos.volume
pos_type = pos.type
print(f"Debug Posición: ticket={TICKET}, type={pos_type}, volume={volume}, symbol={symbol}")

order_type = mt5.ORDER_TYPE_SELL if pos_type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
tick = mt5.symbol_info_tick(symbol)
if not tick:
    print("No se pudo obtener el precio del símbolo")
    mt5.shutdown()
    exit()

price = tick.bid if pos_type == mt5.POSITION_TYPE_BUY else tick.ask

close_request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": symbol,
    "volume": volume,
    "type": order_type,
    "position": TICKET,
    "price": price,
    "magic": 20240725,
    "comment": "Cierre manual debug",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC
}

print("Enviando solicitud de cierre:", close_request)
result = mt5.order_send(close_request)
print("Resultado de cierre:", result)
mt5.shutdown()
