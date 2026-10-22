from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app.api import schemas as S
from app.api import service
from app.connections import (
    DecryptError, build_url, check_connection, decrypt_url, encrypt_url, mask_secrets, mask_url,
)
from app.mapping.introspect import normalise_type
from app.mapping.joins import validate_join_plan
from app.mapping.types import ColumnRef, dump, load_join_plan, load_profile
from app.mapping.viewgen import PublishError, build_base_select, build_view_ddl, preview, publish
from app.store import Connection, MappingRun, Publication

router = APIRouter(prefix="/api")


def _ctx(request: Request):
    return request.app.state


def _connection_out(c: Connection, key: str) -> S.ConnectionOut:
    try:
        masked, needs = mask_url(decrypt_url(c.url_encrypted, key)), False
    except DecryptError:
        masked, needs = None, True
    return S.ConnectionOut(id=c.id, name=c.name, dialect=c.dialect, url_masked=masked,
                           schemas=c.schemas, needs_password=needs)


def _get(s, model, id_):
    obj = s.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__tablename__} {id_} not found")
    return obj


def _url(conn: Connection, key: str) -> str:
    try:
        return decrypt_url(conn.url_encrypted, key)
    except DecryptError as exc:
        raise HTTPException(409, f"{exc}; re-enter the password") from exc


# ---- catalog & connections ------------------------------------------------------------------

@router.get("/catalog")
def get_catalog(request: Request):
    return _ctx(request).catalog.model_dump()


@router.get("/connections", response_model=list[S.ConnectionOut])
def list_connections(request: Request):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        return [_connection_out(c, ctx.settings.secret_key) for c in s.query(Connection).order_by(Connection.name)]


@router.post("/connections", response_model=S.ConnectionOut, status_code=201)
def create_connection(body: S.ConnectionIn, request: Request):
    if not body.password:
        raise HTTPException(422, "password is required")
    ctx = _ctx(request)
    url = build_url(body.dialect, body.host, body.port, body.database, body.user, body.password)
    with ctx.store.session() as s:
        c = Connection(name=body.name, dialect=body.dialect, schemas=body.schemas,
                       url_encrypted=encrypt_url(url, ctx.settings.secret_key))
        s.add(c)
        try:
            s.commit()
        except IntegrityError:
            raise HTTPException(409, f"a connection named {body.name!r} already exists") from None
        return _connection_out(c, ctx.settings.secret_key)


@router.put("/connections/{cid}", response_model=S.ConnectionOut)
def update_connection(cid: int, body: S.ConnectionIn, request: Request):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        c = _get(s, Connection, cid)
        password = body.password
        if not password:
            from sqlalchemy import make_url
            password = make_url(_url(c, ctx.settings.secret_key)).password
        url = build_url(body.dialect, body.host, body.port, body.database, body.user, password)
        c.name, c.dialect, c.schemas = body.name, body.dialect, body.schemas
        c.url_encrypted = encrypt_url(url, ctx.settings.secret_key)
        try:
            s.commit()
        except IntegrityError:
            raise HTTPException(409, f"a connection named {body.name!r} already exists") from None
        return _connection_out(c, ctx.settings.secret_key)


@router.delete("/connections/{cid}", status_code=204)
def delete_connection(cid: int, request: Request):
    with _ctx(request).store.session() as s:
        s.delete(_get(s, Connection, cid))
        s.commit()
    return Response(status_code=204)


@router.post("/connections/{cid}/test", response_model=S.TestResultOut)
def test_connection_route(cid: int, request: Request):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        c = _get(s, Connection, cid)
        url, schemas = _url(c, ctx.settings.secret_key), list(c.schemas)
    r = check_connection(url, schemas)
    return S.TestResultOut(ok=r.ok, tables=r.tables, error=r.error)


@router.get("/connections/{cid}/columns", response_model=list[S.ColumnOut])
def list_columns(cid: int, request: Request):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        c = _get(s, Connection, cid)
        url, schemas = _url(c, ctx.settings.secret_key), list(c.schemas)
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        return [S.ColumnOut(schema=sc, table=t, column=col["name"], type=normalise_type(col["type"]))
                for sc in schemas for t in insp.get_table_names(schema=sc)
                for col in insp.get_columns(t, schema=sc)]
    except Exception as exc:
        raise HTTPException(502, mask_secrets(str(exc), url)) from None
    finally:
        engine.dispose()


# ---- mapping runs -------------------------------------------------------------------------------

def _detail(run: MappingRun, catalog) -> S.RunDetail:
    entries = []
    for e in run.entries:
        f = catalog.field(e.field_id)
        src = (S.SourceOut(schema=e.source_schema, table=e.source_table, column=e.source_column)
               if e.source_table else None)
        entries.append(S.EntryOut(
            field_id=e.field_id, label=f.label, section=f.section, required=f.required_for_mapping,
            source=src, score=e.score, decided_by=e.decided_by, reason=e.reason, warnings=e.warnings,
            candidates=[S.CandidateOut(**c) for c in e.candidates], status=e.status))
    ready = run.status in ("ready", "published")
    return S.RunDetail(
        run=S.RunOut.model_validate(run, from_attributes=True), join_plan=run.join_plan, entries=entries,
        blockers=service.blockers(run, catalog),
        affected_calculated=service.affected_calculated(run, catalog) if ready else [])


@router.post("/connections/{cid}/mapping-runs", response_model=S.RunStarted, status_code=202)
def start_run(cid: int, body: S.RunStart, request: Request, tasks: BackgroundTasks):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        c = _get(s, Connection, cid)
        _url(c, ctx.settings.secret_key)
        run = MappingRun(connection_id=cid, catalog_version=ctx.catalog.version, layers=body.layers,
                         status="running")
        s.add(run)
        s.commit()
        run_id = run.id
    tasks.add_task(service.execute_run, ctx.store, run_id, ctx.catalog, ctx.settings, ctx.embedder(), ctx.llm)
    return S.RunStarted(run_id=run_id, status="running")


@router.get("/mapping-runs/{rid}", response_model=S.RunDetail)
def get_run(rid: int, request: Request):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        return _detail(_get(s, MappingRun, rid), ctx.catalog)


@router.get("/connections/{cid}/mapping-runs/latest", response_model=S.RunDetail)
def latest_run(cid: int, request: Request):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        run = s.query(MappingRun).filter_by(connection_id=cid).order_by(MappingRun.id.desc()).first()
        if run is None:
            raise HTTPException(404, f"no mapping runs for connection {cid}")
        return _detail(run, ctx.catalog)


def _ready_run(s, rid: int) -> MappingRun:
    run = _get(s, MappingRun, rid)
    if run.status not in ("ready", "published"):
        raise HTTPException(409, f"run {rid} is {run.status}")
    return run


@router.patch("/mapping-runs/{rid}/entries/{field_id}", response_model=S.EntryOut)
def patch_entry(rid: int, field_id: str, body: S.EntryPatch, request: Request):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        run = _ready_run(s, rid)
        ref = ColumnRef(body.schema_, body.table, body.column) if body.action == "choose" else None
        try:
            service.edit_entry(run, field_id, body.action, ref, ctx.catalog)
        except service.EditError as exc:
            raise HTTPException(exc.status, exc.detail) from None
        s.commit()
        return next(e for e in _detail(run, ctx.catalog).entries if e.field_id == field_id)


@router.post("/mapping-runs/{rid}/accept-above")
def accept_above(rid: int, body: S.AcceptAbove, request: Request):
    with _ctx(request).store.session() as s:
        run = _ready_run(s, rid)
        n = 0
        for e in run.entries:
            if e.status == "suggested" and e.source_table and e.score >= body.threshold:
                e.status, n = "accepted", n + 1
        if n and run.status == "published":
            run.status = "ready"
        s.commit()
        return {"accepted": n}


@router.put("/mapping-runs/{rid}/join-plan", response_model=S.RunDetail)
def put_join_plan(rid: int, body: S.JoinPlanIn, request: Request):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        run = _ready_run(s, rid)
        try:
            plan = load_join_plan(body.join_plan)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, f"malformed join plan: {exc}") from None
        engine, info = service.current_info(_url(run.connection, ctx.settings.secret_key), run)
        engine.dispose()
        errors = validate_join_plan(plan, info, [load_profile(p) for p in run.profiles])
        if errors:
            raise HTTPException(422, errors)
        run.join_plan, run.join_plan_confirmed = dump(plan), body.confirmed
        grain_entry = next(e for e in run.entries if e.field_id == "application_id")
        grain_entry.source_schema, grain_entry.source_table, grain_entry.source_column = (
            plan.grain.schema, plan.grain.table, plan.grain.column)
        if run.status == "published":
            run.status = "ready"
        s.commit()
        return _detail(run, ctx.catalog)


def _base_select(run: MappingRun, info, catalog):
    sources = {e.field_id: service.entry_source(e) for e in run.entries}
    try:
        return build_base_select(info, load_join_plan(run.join_plan), sources, catalog)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/mapping-runs/{rid}/preview", response_model=S.PreviewOut)
def preview_run(rid: int, request: Request, limit: int = 20):
    ctx = _ctx(request)
    with ctx.store.session() as s:
        run = _ready_run(s, rid)
        url = _url(run.connection, ctx.settings.secret_key)
        engine, info = service.current_info(url, run)
        try:
            columns, rows = preview(engine, _base_select(run, info, ctx.catalog), ctx.catalog, min(limit, 200))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, mask_secrets(str(exc), url)) from None
        finally:
            engine.dispose()
        return S.PreviewOut(columns=columns, rows=rows)


@router.post("/mapping-runs/{rid}/publish", response_model=S.PublishOut)
def publish_run(rid: int, request: Request):
    ctx = _ctx(request)
    schema = ctx.settings.publish_schema
    with ctx.store.session() as s:
        run = _get(s, MappingRun, rid)
        found = service.blockers(run, ctx.catalog)
        if found:
            raise HTTPException(409, {"blockers": found})
        url = _url(run.connection, ctx.settings.secret_key)
        engine, info = service.current_info(url, run)
        try:
            statements = build_view_ddl(info.dialect, schema, _base_select(run, info, ctx.catalog), ctx.catalog)
            result = publish(engine, statements, load_join_plan(run.join_plan).grain, schema)
        except PublishError as exc:
            raise HTTPException(500, {"error": mask_secrets(str(exc), url)}) from None
        finally:
            engine.dispose()
        s.add(Publication(run_id=run.id, schema=schema, ddl=result.ddl, row_count=result.row_count))
        run.status = "published"
        s.commit()
        return S.PublishOut(ddl=result.ddl, row_count=result.row_count, schema=schema)
