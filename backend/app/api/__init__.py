from functools import cache

from cryptography.fernet import Fernet
from fastapi import FastAPI

from app.catalog.loader import load_catalog
from app.mapping.matcher.embed import Embedder
from app.mapping.matcher.llm import LlmMatcher, OpenAIChatClient
from app.settings import Settings
from app.store import Store

KEYGEN = 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'


def create_app(settings: Settings, embedder: Embedder | None = None, llm: LlmMatcher | None = None) -> FastAPI:
    if not settings.secret_key:
        raise RuntimeError(f"BANKREPORTER_SECRET_KEY is not set; generate one with: {KEYGEN}")
    try:
        Fernet(settings.secret_key.encode())
    except (ValueError, TypeError):
        raise RuntimeError(f"BANKREPORTER_SECRET_KEY is not a valid Fernet key; generate one with: {KEYGEN}") from None

    from app.api.routes import router

    app = FastAPI(title="BankReporter")
    app.state.settings = settings
    app.state.catalog = load_catalog(settings.catalog_path)
    app.state.store = Store(settings.db_url)
    app.state.embedder = cache(lambda: embedder or Embedder())   # model loads on first run
    if llm is None and settings.openai_api_key:
        llm = LlmMatcher(OpenAIChatClient(settings.openai_api_key), settings.llm_model)
    app.state.llm = llm
    app.include_router(router)
    return app
