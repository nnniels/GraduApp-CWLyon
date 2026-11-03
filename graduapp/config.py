import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    DATABASE_PATH = os.environ.get("DATABASE_PATH", "instance/graduapp.sqlite")
    CONTENT_DIR = os.environ.get("CONTENT_DIR", "content")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
