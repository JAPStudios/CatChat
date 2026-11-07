"""CatChat's SQLite-backed direct and group messaging service.

The HTTP API is transport-neutral so web, mobile and desktop clients can use
the same accounts, conversations, message history and read receipts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from functools import wraps
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, stream_with_context
from werkzeug.security import check_password_hash, generate_password_hash

_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_CONVERSATION_ID = re.compile(r"^[a-f0-9]{32}$")
_MAX_MESSAGE_CHARS = 4000
_SESSION_SECONDS = 60 * 60 * 24 * 30


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10, isolation_level="DEFERRED")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _initialize(path: str, bot_username: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            is_bot INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('direct', 'group')),
            name TEXT,
            direct_key TEXT UNIQUE,
            agent_session_id TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS participants (
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            last_read_message_id INTEGER,
            joined_at REAL NOT NULL,
            PRIMARY KEY(conversation_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS participants_user ON participants(user_id);
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            sender_id TEXT NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            reply_to_message_id INTEGER UNIQUE REFERENCES messages(id),
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(conversations)").fetchall()}
        if "agent_session_id" not in columns:
            db.execute("ALTER TABLE conversations ADD COLUMN agent_session_id TEXT")
        existing = db.execute(
            "SELECT id FROM users WHERE username=? COLLATE NOCASE", (bot_username,)
        ).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO users(id, username, display_name, password_hash, is_bot, created_at) "
                "VALUES (?, ?, ?, '', 1, ?)",
                (uuid.uuid4().hex, bot_username, "Astrologically Intelligent", time.time()),
            )


def create_app(config: dict | None = None, *, ai_responder=None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.getenv("CATCHAT_DATABASE", "data/catchat.sqlite3"),
        AI_USERNAME=os.getenv("CATCHAT_AI_USERNAME", "astrologically-intelligent"),
        AI_BASE_URL=os.getenv("ASTRO_AI_BASE_URL", ""),
        AI_API_TOKEN=os.getenv("ASTRO_AI_API_TOKEN", ""),
        AI_ENDPOINT_ID=os.getenv("ASTRO_AI_ENDPOINT_ID", ""),
        AI_MODEL=os.getenv("ASTRO_AI_MODEL", ""),
        SSE_SECONDS=20,
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if config:
        app.config.update(config)
    bot_username = str(app.config["AI_USERNAME"]).strip()
    if not _USERNAME.fullmatch(bot_username):
        raise ValueError("CATCHAT_AI_USERNAME must be 3–32 letters, numbers, dots, underscores or hyphens.")
    _initialize(app.config["DATABASE"], bot_username)

    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = _connect(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    def current_user():
        token = request.headers.get("Authorization", "")
        if not token.startswith("Bearer "):
            return None
        raw = token[7:].strip()
        if not raw or len(raw) > 256:
            return None
        return db().execute(
            "SELECT u.id, u.username, u.display_name, u.is_bot "
            "FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>?",
            (_token_digest(raw), time.time()),
        ).fetchone()

    def require_auth(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return jsonify(error="unauthorized"), 401
            g.user = user
            return fn(*args, **kwargs)
        return wrapped

    def is_member(conversation_id: str, user_id: str) -> bool:
        return db().execute(
            "SELECT 1 FROM participants WHERE conversation_id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone() is not None

    def conversation_exists(conversation_id: str) -> bool:
        return bool(_CONVERSATION_ID.fullmatch(conversation_id or "")) and db().execute(
            "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone() is not None

    def message_json(row):
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "sender": row["username"],
            "display_name": row["display_name"],
            "content": row["body"],
            "created_at": row["created_at"],
            "is_agent": bool(row["is_bot"]),
            "reply_to_message_id": row["reply_to_message_id"],
        }

    def fetch_messages(conversation_id: str, after_id: int = 0, limit: int = 50):
        return db().execute(
            "SELECT m.id, m.conversation_id, m.body, m.created_at, m.reply_to_message_id, "
            "u.username, u.display_name, u.is_bot FROM messages m "
            "JOIN users u ON u.id=m.sender_id "
            "WHERE m.conversation_id=? AND m.id>? ORDER BY m.id ASC LIMIT ?",
            (conversation_id, after_id, limit),
        ).fetchall()

    def request_agent_reply(conversation_id: str, message_id: int):
        bot = db().execute(
            "SELECT id FROM users WHERE username=? COLLATE NOCASE",
            (app.config["AI_USERNAME"],),
        ).fetchone()
        if bot is None or not is_member(conversation_id, bot["id"]):
            return None
        previous = db().execute(
            "SELECT m.id, m.conversation_id, m.body, m.created_at, m.reply_to_message_id, "
            "u.username, u.display_name, u.is_bot FROM messages m "
            "JOIN users u ON u.id=m.sender_id WHERE m.reply_to_message_id=?",
            (message_id,),
        ).fetchone()
        if previous:
            return message_json(previous)
        source = db().execute(
            "SELECT m.body, m.sender_id, u.is_bot FROM messages m "
            "JOIN users u ON u.id=m.sender_id WHERE m.id=? AND m.conversation_id=?",
            (message_id, conversation_id),
        ).fetchone()
        if source is None or source["is_bot"]:
            return None
        if ai_responder is not None:
            answer = ai_responder(source["body"], "catchat_" + conversation_id)
        else:
            base_url = str(app.config["AI_BASE_URL"] or "").strip().rstrip("/") + "/"
            token = str(app.config["AI_API_TOKEN"] or "").strip()
            endpoint_id = str(app.config["AI_ENDPOINT_ID"] or "").strip()
            model = str(app.config["AI_MODEL"] or "").strip()
            parsed = urllib.parse.urlsplit(base_url)
            if (
                not base_url or not token or not endpoint_id or not model
                or parsed.scheme not in {"https", "http"}
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment
            ):
                raise RuntimeError(
                    "Astrologically Intelligent is not configured. Set ASTRO_AI_BASE_URL, "
                    "ASTRO_AI_API_TOKEN, ASTRO_AI_ENDPOINT_ID and ASTRO_AI_MODEL."
                )
            if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise RuntimeError("ASTRO_AI_BASE_URL must use HTTPS outside loopback.")

            session_row = db().execute(
                "SELECT agent_session_id FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            ai_session_id = session_row["agent_session_id"] if session_row else None
            if not ai_session_id:
                form = urllib.parse.urlencode({
                    "name": "CatChat " + conversation_id[:8],
                    "endpoint_id": endpoint_id,
                    "model": model,
                }).encode("utf-8")
                session_request = urllib.request.Request(
                    urllib.parse.urljoin(base_url, "api/session"), data=form, method="POST",
                    headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                )
                try:
                    with urllib.request.urlopen(session_request, timeout=30) as response:
                        raw_session = response.read(100_001)
                        if len(raw_session) > 100_000:
                            raise RuntimeError("Astrologically Intelligent session response exceeded its limit.")
                        session_payload = json.loads(raw_session)
                except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                    raise RuntimeError("Could not create the Astrologically Intelligent conversation session.") from exc
                ai_session_id = session_payload.get("id") if isinstance(session_payload, dict) else None
                if not isinstance(ai_session_id, str) or not ai_session_id:
                    raise RuntimeError("Astrologically Intelligent did not return a session identifier.")
                db().execute(
                    "UPDATE conversations SET agent_session_id=? WHERE id=?",
                    (ai_session_id, conversation_id),
                )
                db().commit()

            chat_payload = json.dumps({
                "message": source["body"],
                "session": ai_session_id,
            }).encode("utf-8")
            chat_request = urllib.request.Request(
                urllib.parse.urljoin(base_url, "api/chat"), data=chat_payload, method="POST",
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(chat_request, timeout=180) as response:
                    raw_result = response.read(1_000_001)
                    if len(raw_result) > 1_000_000:
                        raise RuntimeError("Astrologically Intelligent response exceeded the 1 MB limit.")
                    result = json.loads(raw_result)
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                raise RuntimeError("Astrologically Intelligent could not complete the direct message.") from exc
            answer = result.get("response") if isinstance(result, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Astrologically Intelligent returned an empty response.")
        now = time.time()
        cursor = db().execute(
            "INSERT INTO messages(conversation_id, sender_id, body, reply_to_message_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, bot["id"], answer.strip()[:_MAX_MESSAGE_CHARS], message_id, now),
        )
        row = db().execute(
            "SELECT m.id, m.conversation_id, m.body, m.created_at, m.reply_to_message_id, "
            "u.username, u.display_name, u.is_bot FROM messages m "
            "JOIN users u ON u.id=m.sender_id WHERE m.id=?",
            (cursor.lastrowid,),
        ).fetchone()
        db().commit()
        return message_json(row)

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", service="catchat")

    @app.post("/v1/accounts")
    def register():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="invalid_json"), 400
        username = str(payload.get("username") or "").strip()
        password = payload.get("password")
        display_name = str(payload.get("display_name") or username).strip()
        if not _USERNAME.fullmatch(username) or username.casefold() == bot_username.casefold():
            return jsonify(error="invalid_username"), 400
        if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
            return jsonify(error="password_must_be_12_to_256_characters"), 400
        if not display_name or len(display_name) > 80:
            return jsonify(error="invalid_display_name"), 400
        user_id = uuid.uuid4().hex
        try:
            db().execute(
                "INSERT INTO users(id, username, display_name, password_hash, is_bot, created_at) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                (user_id, username, display_name, generate_password_hash(password), time.time()),
            )
            db().commit()
        except sqlite3.IntegrityError:
            return jsonify(error="username_unavailable"), 409
        return jsonify(id=user_id, username=username, display_name=display_name), 201

    @app.post("/v1/sessions")
    def login():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="invalid_json"), 400
        username = str(payload.get("username") or "").strip()
        password = payload.get("password")
        row = db().execute(
            "SELECT id, username, display_name, password_hash, is_bot FROM users "
            "WHERE username=? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if row is None or row["is_bot"] or not isinstance(password, str) or not check_password_hash(row["password_hash"], password):
            return jsonify(error="invalid_credentials"), 401
        token = secrets.token_urlsafe(40)
        now = time.time()
        db().execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_token_digest(token), row["id"], now, now + _SESSION_SECONDS),
        )
        db().commit()
        return jsonify(token=token, expires_at=now + _SESSION_SECONDS, user={
            "id": row["id"], "username": row["username"], "display_name": row["display_name"],
        })

    @app.delete("/v1/sessions")
    @require_auth
    def logout():
        token = request.headers.get("Authorization", "")[7:].strip()
        db().execute("DELETE FROM sessions WHERE token_hash=?", (_token_digest(token),))
        db().commit()
        return jsonify(status="ok")

    @app.post("/v1/conversations/direct")
    @require_auth
    def create_direct():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="invalid_json"), 400
        recipient_name = str(payload.get("recipient_username") or "").strip()
        recipient = db().execute(
            "SELECT id, username FROM users WHERE username=? COLLATE NOCASE", (recipient_name,)
        ).fetchone()
        if recipient is None or recipient["id"] == g.user["id"]:
            return jsonify(error="recipient_not_found"), 404
        direct_key = ":".join(sorted((g.user["id"], recipient["id"])))
        row = db().execute(
            "SELECT id FROM conversations WHERE direct_key=?", (direct_key,)
        ).fetchone()
        if row is None:
            conversation_id = uuid.uuid4().hex
            now = time.time()
            db().execute(
                "INSERT INTO conversations(id, kind, direct_key, created_at) VALUES (?, 'direct', ?, ?)",
                (conversation_id, direct_key, now),
            )
            db().executemany(
                "INSERT INTO participants(conversation_id, user_id, joined_at) VALUES (?, ?, ?)",
                [(conversation_id, g.user["id"], now), (conversation_id, recipient["id"], now)],
            )
            db().commit()
        else:
            conversation_id = row["id"]
        return jsonify(conversation_id=conversation_id, kind="direct"), 200

    @app.post("/v1/conversations/group")
    @require_auth
    def create_group():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="invalid_json"), 400
        name = str(payload.get("name") or "").strip()
        usernames = payload.get("participants")
        if not name or len(name) > 80 or not isinstance(usernames, list) or not 1 <= len(usernames) <= 49:
            return jsonify(error="invalid_group"), 400
        names_by_key = {g.user["username"].casefold(): g.user["username"]}
        for item in usernames:
            if isinstance(item, str) and item.strip():
                cleaned = item.strip()
                names_by_key.setdefault(cleaned.casefold(), cleaned)
        names = list(names_by_key.values())
        if len(names) < 2 or len(names) > 50:
            return jsonify(error="invalid_group_participants"), 400
        placeholders = ",".join("?" for _ in names)
        users = db().execute(
            f"SELECT id, username FROM users WHERE username COLLATE NOCASE IN ({placeholders})",
            names,
        ).fetchall()
        if len(users) != len(names):
            return jsonify(error="participant_not_found"), 404
        conversation_id = uuid.uuid4().hex
        now = time.time()
        db().execute(
            "INSERT INTO conversations(id, kind, name, created_at) VALUES (?, 'group', ?, ?)",
            (conversation_id, name, now),
        )
        db().executemany(
            "INSERT INTO participants(conversation_id, user_id, joined_at) VALUES (?, ?, ?)",
            [(conversation_id, user["id"], now) for user in users],
        )
        db().commit()
        return jsonify(conversation_id=conversation_id, kind="group", name=name), 201

    @app.get("/v1/conversations")
    @require_auth
    def list_conversations():
        rows = db().execute(
            "SELECT c.id, c.kind, c.name, c.created_at, "
            "(SELECT m.body FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message, "
            "(SELECT m.created_at FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message_at "
            "FROM conversations c JOIN participants p ON p.conversation_id=c.id "
            "WHERE p.user_id=? ORDER BY COALESCE(last_message_at, c.created_at) DESC",
            (g.user["id"],),
        ).fetchall()
        return jsonify(conversations=[dict(row) for row in rows])

    @app.get("/v1/conversations/<conversation_id>/messages")
    @require_auth
    def list_messages(conversation_id):
        if not conversation_exists(conversation_id):
            return jsonify(error="conversation_not_found"), 404
        if not is_member(conversation_id, g.user["id"]):
            return jsonify(error="forbidden"), 403
        try:
            after_id = int(request.args.get("after_id", "0"))
            limit = int(request.args.get("limit", "50"))
        except ValueError:
            return jsonify(error="invalid_pagination"), 400
        if after_id < 0 or not 1 <= limit <= 100:
            return jsonify(error="invalid_pagination"), 400
        rows = fetch_messages(conversation_id, after_id, limit)
        return jsonify(messages=[message_json(row) for row in rows])

    @app.post("/v1/conversations/<conversation_id>/messages")
    @require_auth
    def send_message(conversation_id):
        if not conversation_exists(conversation_id):
            return jsonify(error="conversation_not_found"), 404
        if not is_member(conversation_id, g.user["id"]):
            return jsonify(error="forbidden"), 403
        payload = request.get_json(silent=True)
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str) or not content.strip() or len(content) > _MAX_MESSAGE_CHARS:
            return jsonify(error="message_must_be_1_to_4000_characters"), 400
        cursor = db().execute(
            "INSERT INTO messages(conversation_id, sender_id, body, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, g.user["id"], content.strip(), time.time()),
        )
        db().commit()
        user_message_id = cursor.lastrowid
        bot = db().execute(
            "SELECT id FROM users WHERE username=? COLLATE NOCASE", (bot_username,)
        ).fetchone()
        agent_reply = None
        if bot and is_member(conversation_id, bot["id"]) and g.user["id"] != bot["id"]:
            try:
                agent_reply = request_agent_reply(conversation_id, user_message_id)
            except RuntimeError as exc:
                return jsonify(error="agent_reply_failed", detail=str(exc), message_id=user_message_id), 502
        rows = fetch_messages(conversation_id, user_message_id - 1, 2)
        return jsonify(messages=[message_json(row) for row in rows]), 201

    @app.post("/v1/conversations/<conversation_id>/read")
    @require_auth
    def mark_read(conversation_id):
        if not conversation_exists(conversation_id):
            return jsonify(error="conversation_not_found"), 404
        if not is_member(conversation_id, g.user["id"]):
            return jsonify(error="forbidden"), 403
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="invalid_json"), 400
        message_id = payload.get("message_id")
        if message_id is None:
            row = db().execute(
                "SELECT MAX(id) AS latest FROM messages WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            message_id = row["latest"] or 0
        if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id < 0:
            return jsonify(error="invalid_message_id"), 400
        exists = db().execute(
            "SELECT 1 FROM messages WHERE id=? AND conversation_id=?",
            (message_id, conversation_id),
        ).fetchone() if message_id else True
        if not exists:
            return jsonify(error="message_not_found"), 404
        db().execute(
            "UPDATE participants SET last_read_message_id=? WHERE conversation_id=? AND user_id=?",
            (message_id, conversation_id, g.user["id"]),
        )
        db().commit()
        return jsonify(status="ok", last_read_message_id=message_id)

    @app.get("/v1/conversations/<conversation_id>/events")
    @require_auth
    def events(conversation_id):
        if not conversation_exists(conversation_id):
            return jsonify(error="conversation_not_found"), 404
        if not is_member(conversation_id, g.user["id"]):
            return jsonify(error="forbidden"), 403
        try:
            after_id = max(0, int(request.args.get("after_id", "0")))
        except ValueError:
            return jsonify(error="invalid_pagination"), 400
        owner_id = g.user["id"]
        duration = max(1, min(int(app.config["SSE_SECONDS"]), 30))

        @stream_with_context
        def stream():
            cursor = after_id
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                rows = fetch_messages(conversation_id, cursor, 100)
                for row in rows:
                    cursor = row["id"]
                    yield "id: " + str(cursor) + "\ndata: " + json.dumps(message_json(row)) + "\n\n"
                if not rows:
                    yield ": keep-alive\n\n"
                time.sleep(1)
            yield "event: close\ndata: {}\n\n"

        response = Response(stream(), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("CATCHAT_HOST", "127.0.0.1"),
        port=int(os.getenv("CATCHAT_PORT", "7800")),
        threaded=True,
    )
