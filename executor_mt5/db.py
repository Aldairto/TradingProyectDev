from dotenv import load_dotenv
import mysql.connector
import os
from datetime import datetime

load_dotenv()

# Si estás corriendo local, asegúrate de cargar el .env antes de esto:
# from dotenv import load_dotenv
# load_dotenv()

# Lee los datos de conexión desde variables de entorno
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

# ---------- OPERACIONES EN TABLA orders ----------
def insert_order(order_type, price, symbol):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO orders (order_type, price, symbol, status) VALUES (%s, %s, %s, 'pending')",
            (order_type, price, symbol)
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB] Orden guardada en MySQL: {order_type} {symbol} @ {price}")
    except Exception as e:
        print(f"[DB ERROR] Al guardar la orden: {e}")

def get_pending_orders():
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM orders WHERE status='pending'")
        orders = cur.fetchall()
        cur.close()
        conn.close()
        return orders
    except Exception as e:
        print(f"[DB ERROR] Al leer órdenes pendientes: {e}")
        return []

def update_order_status(order_id, new_status):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status=%s WHERE id=%s", (new_status, order_id))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB] Estado de orden {order_id} actualizado a {new_status}")
    except Exception as e:
        print(f"[DB ERROR] Al actualizar estatus de orden: {e}")

# ---------- OPERACIONES EN TABLA trades_log ----------
def insertar_ejecucion(order_id, ticket, symbol, side, volume, entry_price, tp, sl, open_time):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trades_log (order_id, ticket, symbol, side, volume, entry_price, tp, sl, open_time, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (order_id, ticket, symbol, side, volume, entry_price, tp, sl, open_time, 'open'))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB] Trade ABIERTO registrado. Ticket {ticket} | {side} {symbol} @ {entry_price}")
    except Exception as e:
        print(f"[DB ERROR] Al registrar trade abierto: {e}")

def registrar_trade_cerrado(ticket, exit_price, close_time, comment=""):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE trades_log
            SET exit_price=%s, close_time=%s, status='closed', comment=%s
            WHERE ticket=%s
        """, (exit_price, close_time, comment, ticket))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB] Trade CERRADO. Ticket {ticket} | Exit {exit_price} at {close_time}")
    except Exception as e:
        print(f"[DB ERROR] Al cerrar trade: {e}")

def get_open_trades(symbol=None, side=None):
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        query = "SELECT * FROM trades_log WHERE status='open'"
        params = []
        if symbol:
            query += " AND symbol=%s"
            params.append(symbol)
        if side:
            query += " AND side=%s"
            params.append(side)
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"[DB ERROR] Al consultar trades abiertos: {e}")
        return []

# ---------- UTILIDAD ----------
def get_now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
