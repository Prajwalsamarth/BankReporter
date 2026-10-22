"""ASGI entry point: uvicorn app.main:app --reload (from backend/)."""
from app.api import create_app
from app.settings import Settings

app = create_app(Settings())
