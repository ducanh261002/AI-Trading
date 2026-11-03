import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import deque

from fastapi.responses import JSONResponse, RedirectResponse


def password_hash(password):
    if len(password) < 12:
        raise ValueError("Use at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt:" + base64.b64encode(salt).decode() + ":" + base64.b64encode(digest).decode()


def password_valid(password, encoded):
    try:
        label, salt, digest = encoded.split(":")
        if label != "scrypt" or len(password) > 256:
            return False
        expected = base64.b64decode(digest, validate=True)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt, validate=True), n=16384, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Auth:
    def __init__(self, settings, database):
        self.settings, self.database = settings, database
        self.attempts = {}

    def initialize(self):
        with self.database.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS auth_sessions(id TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires_at INTEGER NOT NULL)")

    def session(self, request):
        token = request.cookies.get("atc_session", "")
        if not token or len(token) > 128:
            return None
        with self.database.connect() as con:
            row = con.execute("SELECT csrf,expires_at FROM auth_sessions WHERE id=? AND expires_at>?", (digest(token), int(time.time()))).fetchone()
        return dict(row) if row else None

    def guard(self, request):
        if not self.settings.hosted:
            return None
        public = {"/login", "/login.js", "/style.css", "/auth/login", "/api/health"}
        if request.url.path in public:
            return None
        session = self.session(request)
        if not session:
            return RedirectResponse("/login", status_code=303) if request.url.path == "/" else JSONResponse({"detail": "Authentication required"}, status_code=401)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("x-csrf-token", "")
            if not csrf or not hmac.compare_digest(digest(csrf), session["csrf"]):
                return JSONResponse({"detail": "CSRF token required"}, status_code=403)
        return None

    async def login(self, request):
        if not self.settings.hosted:
            return JSONResponse({"detail": "Local development does not use hosted login"}, status_code=400)
        if request.headers.get("origin") != self.settings.public_origin.rstrip("/"):
            return JSONResponse({"detail": "Same-origin login required"}, status_code=403)
        key = request.client.host if request.client else "unknown"
        timestamp = time.monotonic()
        self.attempts = {k: v for k, v in self.attempts.items() if v and timestamp - v[-1] < 600}
        if len(self.attempts) >= 1000 and key not in self.attempts:
            return JSONResponse({"detail": "Login temporarily limited"}, status_code=429)
        bucket = self.attempts.setdefault(key, deque(maxlen=10))
        while bucket and timestamp - bucket[0] >= 600:
            bucket.popleft()
        if len(bucket) >= 10:
            return JSONResponse({"detail": "Too many login attempts; wait 10 minutes"}, status_code=429)
        bucket.append(timestamp)
        try:
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 2048:
                    return JSONResponse({"detail": "Login body too large"}, status_code=413)
            body = json.loads(raw)
            password = body.get("password", "")
            if not isinstance(password, str) or not password_valid(password, self.settings.admin_password_hash.get_secret_value()):
                return JSONResponse({"detail": "Invalid password"}, status_code=401)
        except (ValueError, AttributeError):
            return JSONResponse({"detail": "Invalid login"}, status_code=400)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.database.connect() as con:
            con.execute("INSERT INTO auth_sessions VALUES(?,?,?)", (digest(token), digest(csrf), int(time.time()) + 28800))
        response = JSONResponse({"authenticated": True})
        response.set_cookie("atc_session", token, max_age=28800, httponly=True, secure=True, samesite="strict")
        response.set_cookie("atc_csrf", csrf, max_age=28800, secure=True, samesite="strict")
        return response

    def logout(self, request):
        with self.database.connect() as con:
            con.execute("DELETE FROM auth_sessions WHERE id=?", (digest(request.cookies.get("atc_session", "")),))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("atc_session", secure=True, samesite="strict")
        response.delete_cookie("atc_csrf", secure=True, samesite="strict")
        return response
