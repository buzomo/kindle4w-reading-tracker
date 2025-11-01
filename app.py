from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import psycopg2
from psycopg2 import pool
import logging

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/save": {"origins": "*"}, r"/logs": {"origins": "*"}})

# データベース接続プール
db_pool = None


def init_db_pool():
    global db_pool
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable is not set")
        raise ValueError("DATABASE_URL environment variable is not set")

    try:
        db_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1, maxconn=5, dsn=DATABASE_URL
        )
        logger.info("Database connection pool initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")
        raise


def get_db_connection():
    try:
        conn = db_pool.getconn()
        logger.info("Database connection acquired from pool")
        return conn
    except Exception as e:
        logger.error(f"Failed to acquire database connection: {e}")
        raise


def release_db_connection(conn):
    try:
        db_pool.putconn(conn)
        logger.info("Database connection released to pool")
    except Exception as e:
        logger.error(f"Failed to release database connection: {e}")


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
        logger.info("Database initialized: kindle_logs table is ready")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        conn.rollback()
    finally:
        cur.close()
        release_db_connection(conn)


@app.route("/save", methods=["POST"])
def save_log():
    """読書ログを保存"""
    try:
        token = request.args.get("token")
        title = request.json.get("title")
        logger.info(f"Received token: {token}, title: {title}")

        if not token or not title:
            logger.warning("Token or title missing")
            return (
                jsonify({"status": "error", "message": "Token or title missing"}),
                400,
            )

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
            logger.info(f"Inserted log: id={log[0]}, title={title}")
            return jsonify(
                {"status": "success", "id": log[0], "created_at": log[1].isoformat()}
            )
        except Exception as e:
            logger.error(f"Failed to insert log: {e}")
            conn.rollback()
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            cur.close()
            release_db_connection(conn)
    except Exception as e:
        logger.error(f"Unexpected error in /save: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@app.route("/logs", methods=["GET"])
def get_logs():
    """読書ログを取得"""
    try:
        token = request.args.get("token")
        if not token:
            logger.warning("Token missing in /logs request")
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
            logger.info(f"Fetched {len(logs)} logs for token: {token}")
            return jsonify({"status": "success", "logs": logs})
        except Exception as e:
            logger.error(f"Failed to fetch logs: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            cur.close()
            release_db_connection(conn)
    except Exception as e:
        logger.error(f"Unexpected error in /logs: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# アプリ起動時にDBプールとテーブルを初期化
init_db_pool()
init_db()

if __name__ == "__main__":
    app.run(debug=True)
