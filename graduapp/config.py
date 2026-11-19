import os

from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    # No default on purpose: create_app refuses to start without one outside debug/testing.
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    DATABASE_PATH = os.environ.get("DATABASE_PATH", "instance/graduapp.sqlite")
    CONTENT_DIR = os.environ.get("CONTENT_DIR", "content")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")  # empty or "change-me" disables /admin
    ADMIN_SESSION_LIFETIME = timedelta(hours=8)
    ADMIN_LOGIN_RATE_LIMIT = "5 per 10 minutes"  # wrong passwords only, per client IP
    DISPLAY_TZ = os.environ.get("DISPLAY_TZ", "Europe/Paris")  # times are stored in UTC
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set COOKIE_SECURE=1 behind the HTTPS tunnel. Leave it off for plain-HTTP tests on the LAN.
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
    # A phone closing its browser must not lose its team.
    PERMANENT_SESSION_LIFETIME = timedelta(days=2)
    # Only wrong codes count. The counter is per team (see web/auth.py).
    JOIN_RATE_LIMIT = "10 per 10 minutes"
    RATELIMIT_STORAGE_URI = "memory://"
