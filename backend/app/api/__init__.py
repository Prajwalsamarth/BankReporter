from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import cache

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI

from app.catalog.loader import load_catalog
from app.mapping.matcher.embed import Embedder
from app.mapping.matcher.llm import LlmMatcher, OpenAIChatClient
from app.reporting.defaults import seed_defaults
from app.reporting.metrics import MetricError, load_metrics
from app.settings import Settings
from app.store import Store

KEYGEN = 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'


def _fail_interrupted_runs(store: Store) -> None:
    """Runs left 'running' by a previous server process will never finish."""
    from datetime import UTC, datetime
    from app.store import MappingRun
    with store.session() as s:
        for run in s.query(MappingRun).filter_by(status="running"):
            run.status, run.finished_at = "failed", datetime.now(UTC)
            run.error = "server restarted while this run was in progress; re-run the mapping"
        s.commit()


def create_app(settings: Settings, embedder: Embedder | None = None, llm: LlmMatcher | None = None,
               today: Callable[[], date] = date.today, now: Callable[[], datetime] | None = None) -> FastAPI:
    if not settings.secret_key:
        raise RuntimeError(f"BANKREPORTER_SECRET_KEY is not set; generate one with: {KEYGEN}")
    try:
        Fernet(settings.secret_key.encode())
    except (ValueError, TypeError):
        raise RuntimeError(f"BANKREPORTER_SECRET_KEY is not a valid Fernet key; generate one with: {KEYGEN}") from None

    from app.api.auth_routes import router as auth_router
    from app.api.reporting import router as reporting_router
    from app.api.routes import router
    from app.auth.scope import get_scope
    from app.auth.sessions import purge_expired

    app = FastAPI(title="BankReporter")
    app.state.settings = settings
    app.state.catalog = load_catalog(settings.catalog_path)
    try:
        app.state.metrics = load_metrics(settings.metrics_path, app.state.catalog)
    except MetricError as exc:
        raise RuntimeError(str(exc)) from None
    app.state.store = Store(settings.db_url)
    _fail_interrupted_runs(app.state.store)
    seed_defaults(app.state.store, settings.defaults_dir)
    app.state.today = today
    app.state.now = now or (lambda: datetime.now(UTC))
    with app.state.store.session() as s:
        purge_expired(s, app.state.now())
        s.commit()
    app.state.embedder = cache(lambda: embedder or Embedder())   # model loads on first run
    if llm is None and settings.openai_api_key:
        llm = LlmMatcher(OpenAIChatClient(settings.openai_api_key), settings.llm_model)
    app.state.llm = llm
    guarded = [Depends(get_scope)]
    app.include_router(auth_router)
    app.include_router(router, dependencies=guarded)
    app.include_router(reporting_router, dependencies=guarded)
    return app
