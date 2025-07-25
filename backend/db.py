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
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM orders WHERE status='pending'")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def set_order_status(order_id, status):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=%s WHERE id=%s", (status, order_id))
    conn.commit()
    cur.close()
    conn.close()
