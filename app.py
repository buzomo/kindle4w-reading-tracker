from flask import Flask, request, jsonify, make_response
import os
import random
import string
import psycopg2
from datetime import datetime

app = Flask(__name__)

# Neon DB接続設定
DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def generate_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


@app.before_request
def setup():
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
    token = request.cookies.get("token")
    title = request.json.get("title")
    if not token or not title:
        return jsonify({"status": "error", "message": "Token or title missing"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    table_name = f"kindle_logs_{''.join(random.choices(string.hexdigits.lower(), k=6))}"
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY,
            token TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    cur.execute(
        f"INSERT INTO {table_name} (token, title) VALUES (%s, %s) RETURNING id, created_at",
        (token, title),
    )
    log = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(
        {"status": "success", "id": log[0], "created_at": log[1].isoformat()}
    )


@app.route("/logs", methods=["GET"])
def get_logs():
    token = request.cookies.get("token")
    if not token:
        return jsonify({"status": "error", "message": "Token missing"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    table_name = f"kindle_logs_{''.join(random.choices(string.hexdigits.lower(), k=6))}"
    cur.execute(
        f"SELECT id, title, created_at FROM {table_name} WHERE token = %s ORDER BY created_at DESC",
        (token,),
    )
    logs = [
        {"id": log[0], "title": log[1], "created_at": log[2].isoformat()}
        for log in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return jsonify({"status": "success", "logs": logs})


if __name__ == "__main__":
    app.run()
