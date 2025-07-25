from dotenv import load_dotenv
load_dotenv()

import MetaTrader5 as mt5
import time
import mysql.connector
import os

MYSQL_HOST = os.environ.get("MYSQL_HOST")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE")

def get_db():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE
    )

def get_pending_orders():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM orders WHERE status='pending'")
    orders = cur.fetchall()
    cur.close()
    conn.close()
    return orders

def set_order_status(order_id, status):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=%s WHERE id=%s", (status, order_id))
    conn.commit()
    cur.close()
    conn.close()

def ejecutar_orden_mt5(order):
    # Aquí pon la lógica real con MT5. Ahora solo imprime la orden.
    print(f"[MT5] Ejecutando: {order['order_type']} {order['symbol']} @ {order['price']}")
    # Lógica real: Aquí deberías abrir posición según tipo de orden, TP, SL, etc.
    # Si ejecuta correctamente:
    return True
    # Si falla: return False

def main():
    if not mt5.initialize():
        print("[MT5 ERROR] Error inicializando MT5")
        return
    print("[MT5] Executor conectado a MT5.")
    while True:
        orders = get_pending_orders()
        print(f"[MT5] {len(orders)} órdenes pendientes encontradas.")
        for order in orders:
            ok = ejecutar_orden_mt5(order)
            if ok:
                set_order_status(order['id'], "executed")
                print(f"[MT5] Orden {order['id']} ejecutada.")
            else:
                set_order_status(order['id'], "error")
                print(f"[MT5] Error ejecutando orden {order['id']}.")
        time.sleep(10)
    mt5.shutdown()

if __name__ == "__main__":
    main()
