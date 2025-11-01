from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import os
import random
import string
import psycopg2
from psycopg2 import pool
from datetime import datetime

app = Flask(__name__)
CORS(app)

# 接続プールの設定
connection_pool = None


def init_db_pool():
    global connection_pool
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set")
    connection_pool = psycopg2.pool.SimpleConnectionPool(
        minconn=1, maxconn=5, dsn=DATABASE_URL
    )
    print("Database connection pool initialized")


def get_db_connection():
    global connection_pool
    if connection_pool is None:
        init_db_pool()
    try:
        conn = connection_pool.getconn()
        print("Database connection acquired from pool")
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        raise


def release_db_connection(conn):
    try:
        connection_pool.putconn(conn)
        print("Database connection released to pool")
    except Exception as e:
        print(f"Database connection release error: {e}")


def init_db():
    """DB初期化: kindle_logsテーブルが存在しない場合に作成"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kindle_logs (
                id SERIAL PRIMARY KEY,
                token TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.commit()
        print("Database initialized: kindle_logs table is ready")
    except Exception as e:
        print(f"Database initialization error: {e}")
        conn.rollback()
    finally:
        cur.close()
        release_db_connection(conn)


def generate_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


@app.before_request
def setup():
    """リクエスト前にトークンを設定"""
    token = request.cookies.get("token")
    if not token and request.args.get("token"):
        token = request.args.get("token")
    if not token:
        token = generate_token()
    resp = make_response()
    resp.set_cookie("token", token, max_age=60 * 60 * 24 * 365 * 10)
    return resp


@app.route("/save", methods=["POST"])
def save_log():
    """読書ログを保存"""
    # 初回呼び出し時にDB初期化
    init_db()

    token = request.args.get("token")
    title = request.json.get("title")
    print(f"Received token: {token}, title: {title}")

    if not token or not title:
        print("Token or title missing")
        return jsonify({"status": "error", "message": "Token or title missing"}), 400

    if title.startswith("*"):
        print("Private page, skipped")
        return jsonify({"status": "error", "message": "Private page"}), 403

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO kindle_logs (token, title) VALUES (%s, %s) RETURNING id, created_at
        """,
            (token, title),
        )
        log = cur.fetchone()
        conn.commit()
        print(f"Inserted log: id={log[0]}, created_at={log[1]}")
        return jsonify(
            {"status": "success", "id": log[0], "created_at": log[1].isoformat()}
        )
    except Exception as e:
        print(f"Error inserting log: {e}")
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@app.route("/logs", methods=["GET"])
def get_logs():
    """読書ログを取得"""
    token = request.cookies.get("token")
    if not token:
        return jsonify({"status": "error", "message": "Token missing"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, title, created_at FROM kindle_logs WHERE token = %s ORDER BY created_at DESC
        """,
            (token,),
        )
        logs = [
            {"id": log[0], "title": log[1], "created_at": log[2].isoformat()}
            for log in cur.fetchall()
        ]
        print(f"Fetched {len(logs)} logs for token: {token}")
        return jsonify({"status": "success", "logs": logs})
    except Exception as e:
        print(f"Error fetching logs: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


if __name__ == "__main__":
    app.run(debug=True)
