import MetaTrader5 as mt5
import time
import json
import os
import openpyxl
from openpyxl import Workbook
from datetime import datetime

ORDERS_FILE = "../data/pending_orders.json"
RESULTS_FILE = "../data/transactions.xlsx"

# === Configuración de gestión de riesgo ===
RIESGO = 0.01         # Riesgo por operación (1%)
SL_PIPS = 200         # Stop Loss en pips (ajusta según tu estrategia)
PIP_VALUE = 0.10      # Valor de un pip por 0.01 lote en XAUUSD (ajusta según símbolo)

def calcular_lote(balance, riesgo, sl_pips, pip_value):
    """
    Calcula el lotaje ideal según balance, % riesgo, tamaño de SL y valor del pip.
    """
    usd_riesgo = balance * riesgo
    lot = usd_riesgo / (sl_pips * pip_value)
    return max(round(lot, 2), 0.01)

def guardar_transaccion_excel(orden, lot, resultado):
    """
    Guarda la orden ejecutada y resultado en un archivo Excel.
    """
    file_exists = os.path.exists(RESULTS_FILE)
    if file_exists:
        wb = openpyxl.load_workbook(RESULTS_FILE)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        # Escribir cabecera
        ws.append([
            "Fecha", "Símbolo", "Tipo", "Precio", "Lote", "SL", "TP1", "Resultado", "OrderID"
        ])
    ws.append([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        orden["symbol"],
        orden["side"],
        orden["price"],
        lot,
        orden["tps"]["SL"],
        orden["tps"]["TP1"],
        getattr(resultado, "retcode", "Error"),
        getattr(resultado, "order", "-")
    ])
    wb.save(RESULTS_FILE)

def ejecutar_orden_mt5(orden, lot):
    symbol = orden["symbol"]
    side = orden["side"]
    price = orden["price"]
    sl = orden["tps"]["SL"]
    tp1 = orden["tps"]["TP1"]

    if not mt5.symbol_select(symbol, True):
        print(f"No se pudo seleccionar el símbolo {symbol}")
        return

    deviation = 20
    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp1,
        "deviation": deviation,
        "magic": 123456,
        "comment": "AutoBot Python",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    print("Enviando orden a MT5:", request)
    result = mt5.order_send(request)
    print("Resultado:", result)
    return result

def main():
    if not mt5.initialize():
        print("Error inicializando MT5")
        return

    while True:
        account_info = mt5.account_info()
        balance = account_info.balance if account_info else 200  # fallback si falla

        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, "r") as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                try:
                    orden = json.loads(line.strip())
                    lot = calcular_lote(balance, RIESGO, SL_PIPS, PIP_VALUE)
                    print(f"Lote calculado: {lot} (Balance: {balance})")
                    result = ejecutar_orden_mt5(orden, lot)
                    guardar_transaccion_excel(orden, lot, result)
                    time.sleep(1)
                except Exception as e:
                    print("Error:", e)
                    new_lines.append(line)

            # Mantiene solo las no ejecutadas
            with open(ORDERS_FILE, "w") as f:
                f.writelines(new_lines)

        time.sleep(5)

    mt5.shutdown()

if __name__ == "__main__":
    main()
