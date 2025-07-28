# mt5_executor.py
import MetaTrader5 as mt5
import time
import os
import mysql.connector
from dotenv import load_dotenv
from datetime import datetime
from mt5_utils import calcular_tps, cerrar_posiciones_hasta_vacio, validar_tp_vs_stop_level

# Carga variables de entorno
load_dotenv()

# MySQL
MYSQL_HOST = os.getenv('MYSQL_HOST')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')

# MT5
MT5_LOGIN = int(os.getenv('MT5_LOGIN'))
MT5_PASSWORD = os.getenv('MT5_PASSWORD')
MT5_SERVER = os.getenv('MT5_SERVER')
MT5_PATH = os.getenv('MT5_PATH')

MAGIC = 20240725
TPS = [0.2, 0.5, 1, 2, 3, 5]

def obtener_ordenes_pendientes():
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM orders WHERE status = 'pending' ORDER BY id ASC")
    ordenes = cursor.fetchall()
    cursor.close()
    conn.close()
    return ordenes

def actualizar_status_orden(orden_id, status):
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (status, orden_id))
    conn.commit()
    cursor.close()
    conn.close()

def ejecutar_orden(orden):
    symbol = orden['symbol'].upper()
    if symbol == "XAUUSD":
        symbol = "GOLD"
    tipo_orden = orden['order_type'].lower()
    price = float(str(orden['price']).replace(',', '.'))
    lot = 0.1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if "buy" in tipo_orden:
        print(f"[LOG] Cerrar posiciones SELL antes de abrir BUY...")
        if not cerrar_posiciones_hasta_vacio(symbol, tipo=mt5.POSITION_TYPE_SELL):
            print("[ERROR] No se pudieron cerrar todas las SELL. Aborto ejecución.")
            return False
        order_type = mt5.ORDER_TYPE_BUY
    elif "sell" in tipo_orden:
        print(f"[LOG] Cerrar posiciones BUY antes de abrir SELL...")
        if not cerrar_posiciones_hasta_vacio(symbol, tipo=mt5.POSITION_TYPE_BUY):
            print("[ERROR] No se pudieron cerrar todas las BUY. Aborto ejecución.")
            return False
        order_type = mt5.ORDER_TYPE_SELL
    else:
        print(f"[ERROR] Tipo de orden desconocido: {tipo_orden}")
        return False

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"[ERROR] No se pudo obtener tick para {symbol}.")
        return False

    # Calcular y validar TP
    tps = calcular_tps(price, TPS)
    tps_validos = validar_tp_vs_stop_level(symbol, tps, order_type)

    ejecuciones = 0
    for i, tp in enumerate(tps_validos):
        print(f"[DEBUG] Ejecutando parcial {i+1}: {tipo_orden} {symbol} @ {price} | TP: {tp}")
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": round(lot / len(tps_validos), 2),
            "type": order_type,
            "price": tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid,
            "tp": tp,
            "magic": MAGIC,
            "comment": f"TP parcial {i+1} auto",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC
        }
        result = mt5.order_send(request)
        if result and hasattr(result, "retcode") and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"[OK] Parcial {i+1} ejecutada. Ticket: {getattr(result, 'order', 'N/A')}")
            ejecuciones += 1
        else:
            print(f"[ERROR] Parcial {i+1} no ejecutada: {getattr(result, 'retcode', 'SIN RESULTADO')} ({getattr(result, 'comment', 'NO DATA')}) result={result}")

    if ejecuciones > 0:
        actualizar_status_orden(orden['id'], "executed")
        print(f"[LOG] {ejecuciones} parciales ejecutadas. Status cambiado a 'executed'.")
    else:
        print(f"[LOG] Ninguna parcial ejecutada. El status sigue como 'pending'.")
    return True

def main():
    print("[LOG] Iniciando MT5 Executor...")
    if not mt5.initialize(MT5_PATH, login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print(f"[ERROR] No se pudo inicializar MT5: {mt5.last_error()}")
        return
    account_info = mt5.account_info()
    if account_info:
        print(f"[MTS] Conectado como {account_info.login}. Balance: {account_info.balance}.")
    else:
        print("[ERROR] No se pudo obtener información de cuenta MT5.")

    while True:
        print("[LOG] Buscando órdenes pendientes en la base de datos...")
        ordenes = obtener_ordenes_pendientes()
        print(f"[LOG] Encontradas {len(ordenes)} órdenes pendientes.")
        for orden in ordenes:
            ejecutar_orden(orden)
        print("[LOG] Ciclo terminado. Esperando 5 segundos...\n")
        time.sleep(5)

if __name__ == "__main__":
    main()
