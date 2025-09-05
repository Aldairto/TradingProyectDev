from dotenv import load_dotenv
import mysql.connector
import os
from datetime import datetime

# En Railway no necesitas load_dotenv(), pero localmente ayuda:
load_dotenv()

# Conexión desde variables de entorno
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

# ---------- ORDERS ----------
def insert_order(order_type, price, symbol, account_login=None, status='pending', source_order_id=None):
    """
    Inserta UNA orden (útil si ya hiciste fan-out en Python).
    Si prefieres fan-out en SQL: INSERT ... SELECT desde counts.enabled=1.
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (order_type, price, symbol, account_login, status, source_order_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (order_type, price, symbol, account_login, status, source_order_id)
        )
        conn.commit()
    except Exception as e:
        print(f"[DB ERROR] insert_order: {e}")
    finally:
        try:
            cur.close(); conn.close()
        except:
            pass

def get_pending_orders(account_login: str):
    """ Devuelve SOLO las órdenes 'pending' de ESTA cuenta (lo usa mt5_executor). """
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT *
            FROM orders
            WHERE account_login = %s
              AND status = 'pending'
            ORDER BY created_at ASC
        """, (account_login,))
        rows = cur.fetchall()
        return rows
    except Exception as e:
        print(f"[DB ERROR] get_pending_orders({account_login}): {e}")
        return []
    finally:
        try:
            cur.close(); conn.close()
        except:
            pass

def update_order_status(order_id: int, account_login: str, new_status: str):
    """ Actualiza el estado de ESA orden para ESTA cuenta. """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE orders
               SET status=%s, updated_at=NOW()
             WHERE id=%s AND account_login=%s
        """, (new_status, order_id, account_login))
        conn.commit()
    except Exception as e:
        print(f"[DB ERROR] update_order_status({order_id},{account_login},{new_status}): {e}")
    finally:
        try:
            cur.close(); conn.close()
        except:
            pass

# --- cuentas activas (tabla counts) ---
def get_active_counts():
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT account_login FROM counts WHERE enabled=1")
        rows = cur.fetchall()
        return [r["account_login"] for r in rows]
    except Exception as e:
        print(f"[DB ERROR] get_active_counts: {e}")
        return []
    finally:
        try:
            cur.close(); conn.close()
        except:
            pass

# ---------- TRADES LOG ----------
def insertar_ejecucion(order_id, ticket, symbol, side, volume, entry_price, tp, sl, open_time):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trades_log (order_id, ticket, symbol, side, volume, entry_price, tp, sl, open_time, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')
        """, (order_id, ticket, symbol, side, volume, entry_price, tp, sl, open_time))
        conn.commit()
    except Exception as e:
        print(f"[DB ERROR] insertar_ejecucion: {e}")
    finally:
        try:
            cur.close(); conn.close()
        except:
            pass

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
    except Exception as e:
        print(f"[DB ERROR] registrar_trade_cerrado: {e}")
    finally:
        try:
            cur.close(); conn.close()
        except:
            pass

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
        return rows
    except Exception as e:
        print(f"[DB ERROR] get_open_trades: {e}")
        return []
    finally:
        try:
            cur.close(); conn.close()
        except:
            pass

def get_now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
