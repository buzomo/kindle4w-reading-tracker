from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import os
import random
import string
import psycopg2
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Neon DB接続設定
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")


def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("Database connected successfully")  # デバッグ用ログ
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")  # デバッグ用ログ
        raise


def generate_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


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
        print("Database initialized: kindle_logs table is ready")  # デバッグ用ログ
    except Exception as e:
        print(f"Database initialization error: {e}")  # デバッグ用ログ
        conn.rollback()
    finally:
        cur.close()
        conn.close()


@app.before_first_request
def initialize():
    """アプリ起動時にDBを初期化"""
    init_db()


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
    token = request.args.get("token")
    title = request.json.get("title")
    print(f"Received token: {token}, title: {title}")  # デバッグ用ログ

    if not token or not title:
        print("Token or title missing")  # デバッグ用ログ
        return jsonify({"status": "error", "message": "Token or title missing"}), 400

    # プライベートページを除外
    if title.startswith("*"):
        print("Private page, skipped")  # デバッグ用ログ
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
        print(f"Inserted log: id={log[0]}, created_at={log[1]}")  # デバッグ用ログ
        return jsonify(
            {"status": "success", "id": log[0], "created_at": log[1].isoformat()}
        )
    except Exception as e:
        print(f"Error inserting log: {e}")  # デバッグ用ログ
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


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
        print(f"Fetched {len(logs)} logs for token: {token}")  # デバッグ用ログ
        return jsonify({"status": "success", "logs": logs})
    except Exception as e:
        print(f"Error fetching logs: {e}")  # デバッグ用ログ
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    app.run(debug=True)
