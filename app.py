from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import psycopg2
from psycopg2 import pool, sql
import logging

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/save": {"origins": "*"}, r"/logs": {"origins": "*"}})

# データベース接続プール
db_pool = None


def init_db_pool():
    """データベース接続プールを初期化"""
    global db_pool
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable is not set")
        raise ValueError("DATABASE_URL environment variable is not set")
    try:
        db_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1, maxconn=5, dsn=DATABASE_URL
        )
        logger.info("Database connection pool initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")
        return False


def create_table_if_not_exists():
    """kindle_logs テーブルを作成（存在しない場合のみ）"""
    if not db_pool:
        logger.error("Database pool is not initialized")
        return False
    conn = None
    try:
        conn = db_pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                CREATE TABLE IF NOT EXISTS kindle_logs (
                    id SERIAL PRIMARY KEY,
                    token TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.commit()
            logger.info("Table 'kindle_logs' is ready")
            return True
    except Exception as e:
        logger.error(f"Failed to create table 'kindle_logs': {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


def add_url_column_if_not_exists():
    """url カラムを追加（存在しない場合のみ）"""
    if not db_pool:
        logger.error("Database pool is not initialized")
        return False
    conn = None
    try:
        conn = db_pool.getconn()
        with conn.cursor() as cur:
            # カラムが存在しない場合のみ追加
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'kindle_logs'
                        AND column_name = 'url'
                    ) THEN
                        EXECUTE 'ALTER TABLE kindle_logs ADD COLUMN url TEXT';
                    END IF;
                END $$;
            """
            )
            conn.commit()
            logger.info("Column 'url' added or already exists in 'kindle_logs'")
            return True
    except Exception as e:
        logger.error(f"Failed to add column 'url' to 'kindle_logs': {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


def get_db_connection():
    """データベース接続を取得"""
    try:
        conn = db_pool.getconn()
        logger.debug("Database connection acquired from pool")
        return conn
    except Exception as e:
        logger.error(f"Failed to acquire database connection: {e}")
        raise


def release_db_connection(conn):
    """データベース接続をプールに戻す"""
    try:
        db_pool.putconn(conn)
        logger.debug("Database connection released to pool")
    except Exception as e:
        logger.error(f"Failed to release database connection: {e}")


# アプリ起動時にDBプールとテーブルを初期化
if not init_db_pool():
    logger.critical("Failed to initialize database pool. Some features may not work.")
else:
    if not create_table_if_not_exists():
        logger.critical(
            "Failed to create table 'kindle_logs'. Some features may not work."
        )
    if not add_url_column_if_not_exists():
        logger.critical(
            "Failed to add column 'url' to 'kindle_logs'. Some features may not work."
        )


@app.route("/save", methods=["POST"])
def save_log():
    """読書ログを保存"""
    if not db_pool:
        logger.error("Database pool is not available")
        return (
            jsonify({"status": "error", "message": "Database connection failed"}),
            500,
        )
    try:
        token = request.args.get("token")
        title = request.json.get("title")
        url = request.json.get("url", None)
        logger.info(f"Received request - token: {token}, title: {title}, url: {url}")
        if not token or not title:
            logger.warning("Token or title missing in request")
            return (
                jsonify({"status": "error", "message": "Token or title missing"}),
                400,
            )
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                WITH last_log AS (
                    SELECT title, url
                    FROM kindle_logs
                    WHERE token = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                )
                INSERT INTO kindle_logs (token, title, url)
                SELECT %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM last_log
                    WHERE last_log.title = %s AND ((last_log.url IS NULL AND %s IS NULL) OR (last_log.url = %s))
                )
                RETURNING id, created_at
                """,
                    (token, title, url),
                )
                log = cur.fetchone()
                conn.commit()
                logger.info(f"Log saved successfully - id: {log[0]}, title: {title}")
                return jsonify(
                    {
                        "status": "success",
                        "id": log[0],
                        "created_at": log[1].isoformat(),
                    }
                )
        except psycopg2.Error as e:
            logger.error(f"Database error while saving log: {e}")
            conn.rollback()
            return jsonify({"status": "error", "message": "Database error"}), 500
        except Exception as e:
            logger.error(f"Unexpected error while saving log: {e}")
            return jsonify({"status": "error", "message": "Internal server error"}), 500
        finally:
            release_db_connection(conn)
    except Exception as e:
        logger.error(f"Unexpected error in /save endpoint: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@app.route("/logs", methods=["GET"])
def get_logs():
    """読書ログを取得"""
    if not db_pool:
        logger.error("Database pool is not available")
        return (
            jsonify({"status": "error", "message": "Database connection failed"}),
            500,
        )
    try:
        token = request.args.get("token")
        if not token:
            logger.warning("Token missing in /logs request")
            return jsonify({"status": "error", "message": "Token missing"}), 400
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, title, url, created_at
                    FROM kindle_logs
                    WHERE token = %s
                    ORDER BY created_at DESC
                """,
                    (token,),
                )
                logs = [
                    {
                        "id": row[0],
                        "title": row[1],
                        "url": row[2],
                        "created_at": row[3].isoformat(),
                    }
                    for row in cur.fetchall()
                ]
                logger.info(f"Retrieved {len(logs)} logs for token: {token}")
                return jsonify({"status": "success", "logs": logs})
        except psycopg2.Error as e:
            logger.error(f"Database error while fetching logs: {e}")
            return jsonify({"status": "error", "message": "Database error"}), 500
        except Exception as e:
            logger.error(f"Unexpected error while fetching logs: {e}")
            return jsonify({"status": "error", "message": "Internal server error"}), 500
        finally:
            release_db_connection(conn)
    except Exception as e:
        logger.error(f"Unexpected error in /logs endpoint: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@app.route("/init-db", methods=["GET"])
def init_db():
    """手動でテーブルを初期化（デバッグ用）"""
    if not db_pool:
        return (
            jsonify({"status": "error", "message": "Database pool not initialized"}),
            500,
        )
    if create_table_if_not_exists() and add_url_column_if_not_exists():
        return jsonify(
            {
                "status": "success",
                "message": "Table and column initialized successfully",
            }
        )
    else:
        return (
            jsonify(
                {"status": "error", "message": "Failed to initialize table or column"}
            ),
            500,
        )


if __name__ == "__main__":
    app.run(debug=True)
