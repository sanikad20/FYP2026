"""
check_services.py — Connectivity check for Campus Chat dependencies
Tests:
  1. PostgreSQL (Port 5432)
  2. Redis (Port 6379)
  3. Ollama (Port 11434)
"""

import os
import sys
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv()


def test_postgresql():
    print("=" * 55)
    print(" 1. PostgreSQL (Database)")
    print("=" * 55)
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", 5432))
    dbname = os.getenv("DB_NAME", "campus_chat")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")

    try:
        import psycopg2

        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=3,
        )
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version_str = cur.fetchone()[0].split(",")[0]

        # Verify table counts
        cur.execute(
            """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """
        )
        tables = [row[0] for row in cur.fetchall()]

        print(f"[OK] CONNECTED successfully to '{dbname}' on {host}:{port}")
        print(f"     Version : {version_str}")
        print(f"     Tables  : {', '.join(tables) if tables else 'None found'}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[FAIL] Could NOT connect to PostgreSQL on {host}:{port}")
        print(f"       Reason: {e}")
        return False


def test_redis():
    print("\n" + "=" * 55)
    print(" 2. Redis (Session & Semantic Cache Store)")
    print("=" * 55)
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", 6379))
    db = int(os.getenv("REDIS_DB", 0))

    try:
        import redis

        r = redis.Redis(host=host, port=port, db=db, socket_timeout=3)
        if r.ping():
            dbsize = r.dbsize()
            print(f"[OK] CONNECTED successfully to Redis on {host}:{port} (db={db})")
            print(f"     PING response : PONG")
            print(f"     Active Keys   : {dbsize}")
            return True
        else:
            print(f"[FAIL] Redis responded but PING was not successful.")
            return False
    except Exception as e:
        print(f"[FAIL] Could NOT connect to Redis on {host}:{port}")
        print(f"       Reason: {e}")
        print(
            "       * Note: The app automatically falls back to in-memory sessions,"
        )
        print(
            "         but Redis is required for persistent sessions and CacheMind."
        )
        return False


def test_ollama():
    print("\n" + "=" * 55)
    print(" 3. Ollama (LLM Engine)")
    print("=" * 55)
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    try:
        req = urllib.request.Request(
            f"{ollama_url}/api/tags",
            headers={"User-Agent": "CampusChatVerifier/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in payload.get("models", [])]
                print(f"[OK] CONNECTED successfully to Ollama at {ollama_url}")
                print(f"     Installed Models ({len(models)}): {', '.join(models) if models else 'None'}")
                needed = ["llama3.2:1b", "llama3"]
                missing = [m for m in needed if not any(m in name for name in models)]
                if missing:
                    print(f"     [!] Notice: Recommended model(s) missing: {missing}")
                    print(f"         Run: ollama pull {' '.join(missing)}")
                return True
            else:
                print(f"[FAIL] Ollama replied with unexpected HTTP {resp.status}")
                return False
    except Exception as e:
        print(f"[FAIL] Could NOT connect to Ollama at {ollama_url}")
        print(f"       Reason: {e}")
        print("       * Start Ollama from your Start menu or run: ollama serve")
        return False


if __name__ == "__main__":
    print("\n>>> Campus Chat Dependency Health Check <<<\n")
    pg_ok = test_postgresql()
    redis_ok = test_redis()
    ollama_ok = test_ollama()

    print("\n" + "=" * 55)
    print(" Summary")
    print("=" * 55)
    print(f" PostgreSQL : {'READY [OK]' if pg_ok else 'OFFLINE [X]'}")
    print(f" Redis      : {'READY [OK]' if redis_ok else 'OFFLINE [X]'}")
    print(f" Ollama     : {'READY [OK]' if ollama_ok else 'OFFLINE [X]'}")
    print("=" * 55 + "\n")
