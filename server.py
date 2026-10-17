"""Small SQLite-backed server for the FINOVA personal finance demo."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_FILE = ROOT / "claro.sqlite3"
SESSIONS: dict[str, int] = {}
COOKIE = "claro_session"


def connect():
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            username_key TEXT NOT NULL UNIQUE,
            password_salt BLOB NOT NULL,
            password_hash BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS movements (
            id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type TEXT NOT NULL CHECK(type IN ('income','expense')), category TEXT NOT NULL,
            title TEXT NOT NULL, amount REAL NOT NULL CHECK(amount > 0), occurred_at TEXT NOT NULL,
            PRIMARY KEY(user_id,id)
        );
        CREATE TABLE IF NOT EXISTS loans (
            id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL, entity TEXT NOT NULL DEFAULT '', principal REAL NOT NULL CHECK(principal > 0),
            paid REAL NOT NULL DEFAULT 0 CHECK(paid >= 0), interest REAL NOT NULL DEFAULT 0,
            interest_type TEXT NOT NULL DEFAULT 'annual', created_at TEXT NOT NULL,
            PRIMARY KEY(user_id,id)
        );
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL, target REAL NOT NULL CHECK(target > 0), saved REAL NOT NULL DEFAULT 0 CHECK(saved >= 0),
            due TEXT NOT NULL DEFAULT '', emoji TEXT NOT NULL DEFAULT '✳',
            PRIMARY KEY(user_id,id)
        );
        CREATE TABLE IF NOT EXISTS events (
            id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('loan','goal')), title TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0), occurred_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(user_id,id)
        );
        CREATE INDEX IF NOT EXISTS movements_user_date ON movements(user_id,occurred_at);
        CREATE INDEX IF NOT EXISTS events_user_date ON events(user_id,occurred_at);
        """)


def password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def send_json(self, payload, status=200, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("La solicitud es demasiado grande.")
        return json.loads(self.rfile.read(length) or b"{}")

    def session_user(self):
        cookie = self.headers.get("Cookie", "")
        token = next((part.strip().split("=", 1)[1] for part in cookie.split(";")
                      if part.strip().startswith(COOKIE + "=")), "")
        return SESSIONS.get(token)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/me":
            user_id = self.session_user()
            if not user_id:
                return self.send_json({"user": None})
            with connect() as db:
                row = db.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
            return self.send_json({"user": row["username"] if row else None})
        if route == "/api/data":
            user_id = self.session_user()
            if not user_id:
                return self.send_json({"error": "Inicia sesión para continuar."}, 401)
            with connect() as db:
                result = {
                    "movements": [dict(r) for r in db.execute("SELECT id,type,category,title,amount,occurred_at AS date FROM movements WHERE user_id=? ORDER BY occurred_at", (user_id,))],
                    "loans": [dict(r) for r in db.execute("SELECT id,name,entity,principal,paid,interest,interest_type AS interestType,created_at AS created FROM loans WHERE user_id=?", (user_id,))],
                    "goals": [dict(r) for r in db.execute("SELECT id,name,target,saved,due,emoji FROM goals WHERE user_id=?", (user_id,))],
                    "events": [dict(r) for r in db.execute("SELECT id,kind,title,amount,occurred_at AS date,note FROM events WHERE user_id=? ORDER BY occurred_at", (user_id,))],
                }
            return self.send_json(result)
        return super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            payload = self.body_json()
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", ""))
            if route == "/api/register":
                if len(username) < 3 or len(username) > 40 or len(password) < 8:
                    return self.send_json({"error": "Usa un usuario de 3 a 40 caracteres y una contraseña de al menos 8."}, 400)
                salt = secrets.token_bytes(16)
                try:
                    with connect() as db:
                        cur = db.execute("INSERT INTO users(username,username_key,password_salt,password_hash) VALUES(?,?,?,?)",
                                         (username, username.casefold(), salt, password_digest(password, salt)))
                        user_id = cur.lastrowid
                except sqlite3.IntegrityError:
                    return self.send_json({"error": "Ese usuario ya existe."}, 409)
                token = secrets.token_urlsafe(32)
                SESSIONS[token] = user_id
                return self.send_json({"user": username}, 201, {"Set-Cookie": f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800"})
            if route == "/api/login":
                with connect() as db:
                    row = db.execute("SELECT id,username,password_salt,password_hash FROM users WHERE username_key=?", (username.casefold(),)).fetchone()
                if not row or not hmac.compare_digest(password_digest(password, row["password_salt"]), row["password_hash"]):
                    return self.send_json({"error": "Usuario o contraseña incorrectos."}, 401)
                token = secrets.token_urlsafe(32)
                SESSIONS[token] = row["id"]
                return self.send_json({"user": row["username"]}, headers={"Set-Cookie": f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800"})
            if route == "/api/logout":
                cookie = self.headers.get("Cookie", "")
                token = next((part.strip().split("=", 1)[1] for part in cookie.split(";") if part.strip().startswith(COOKIE + "=")), "")
                SESSIONS.pop(token, None)
                return self.send_json({"ok": True}, headers={"Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            if route == "/api/data":
                user_id = self.session_user()
                if not user_id:
                    return self.send_json({"error": "Inicia sesión para continuar."}, 401)
                self.save_data(user_id, payload)
                return self.send_json({"ok": True})
            return self.send_json({"error": "Ruta no encontrada."}, 404)
        except (ValueError, TypeError, KeyError, sqlite3.Error) as error:
            return self.send_json({"error": str(error) or "No se pudo procesar la solicitud."}, 400)

    def save_data(self, user_id, data):
        if not isinstance(data, dict):
            raise ValueError("Formato de información inválido.")
        with connect() as db:
            db.execute("BEGIN")
            for table in ("movements", "loans", "goals", "events"):
                db.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            for x in data.get("movements", []):
                db.execute("INSERT INTO movements VALUES(?,?,?,?,?,?,?)", (x["id"],user_id,x["type"],x["category"],x["title"],float(x["amount"]),x["date"]))
            for x in data.get("loans", []):
                db.execute("INSERT INTO loans VALUES(?,?,?,?,?,?,?,?,?)", (x["id"],user_id,x["name"],x.get("entity", ""),float(x["principal"]),float(x.get("paid",0)),float(x.get("interest",0)),x.get("interestType","annual"),x["created"]))
            for x in data.get("goals", []):
                db.execute("INSERT INTO goals VALUES(?,?,?,?,?,?,?)", (x["id"],user_id,x["name"],float(x["target"]),float(x.get("saved",0)),x.get("due", ""),x.get("emoji","✳")))
            for x in data.get("events", []):
                db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)", (x["id"],user_id,x["kind"],x["title"],float(x["amount"]),x["date"],x.get("note", "")))


if __name__ == "__main__":
    init_db()
    address = ("127.0.0.1", 8001)
    print(f"FINOVA disponible en http://localhost:{address[1]}")
    ThreadingHTTPServer(address, Handler).serve_forever()
