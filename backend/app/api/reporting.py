# backend/app/api/reporting.py
"""Reporting & dashboards API (spec §7)."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func
from sqlalchemy.exc import IntegrityError, OperationalError

from app.connections import DecryptError, decrypt_url, mask_secrets
from app.reporting.period import PeriodError, resolve_period
from app.reporting.render import NotPublished, RenderContext, check_published, render_blocks
from app.reporting.spec import check_blocks
from app.store import Connection, Dashboard, MappingRun, Publication, ReportTemplate

router = APIRouter(prefix="/api")
TILE_TYPES = {"kpi", "chart", "table"}
WIDTHS = (3, 4, 6, 8, 12)
HEIGHTS = ("s", "m", "l")


class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    blocks: list[dict]


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    default_period: dict = Field(default_factory=lambda: {"preset": "last_month"})
    tiles: list[dict]


class RenderIn(BaseModel):
    connection_id: int
    period: dict


class RenderBlocksIn(RenderIn):
    blocks: list[dict]


def _state(request: Request):
    return request.app.state


def _get(s, model, id_):
    obj = s.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__tablename__} {id_} not found")
    return obj


def _report_out(t: ReportTemplate) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description, "blocks": t.blocks,
            "updated_at": t.updated_at.isoformat()}


def _dashboard_out(d: Dashboard) -> dict:
    return {"id": d.id, "name": d.name, "default_period": d.default_period, "tiles": d.tiles,
            "updated_at": d.updated_at.isoformat()}


def _check_report(body: ReportIn, st) -> None:
    _, errors = check_blocks(body.blocks, st.catalog, st.metrics)
    if errors:
        raise HTTPException(422, {"errors": errors})


def _check_dashboard(body: DashboardIn, st) -> None:
    errors, seen = [], set()
    for tile in body.tiles:
        tid = tile.get("id")
        msgs = []
        if not tid or tid in seen:
            msgs.append("tiles need a unique id")
        if tile.get("width") not in WIDTHS:
            msgs.append("width must be one of 3, 4, 6, 8, 12")
        if tile.get("height") not in HEIGHTS:
            msgs.append("height must be one of s, m, l")
        if not isinstance(tile.get("block"), dict):
            msgs.append("tiles need a block")
        seen.add(tid)
        if msgs:
            errors.append({"block_id": tid, "messages": msgs})
    _, block_errors = check_blocks([t["block"] for t in body.tiles if isinstance(t.get("block"), dict)],
                                   st.catalog, st.metrics, allowed_types=TILE_TYPES)
    errors += block_errors
    try:
        resolve_period(body.default_period, st.today())
    except PeriodError as exc:
        errors.append({"block_id": None, "messages": [f"default_period: {exc}"]})
    if errors:
        raise HTTPException(422, {"errors": errors})


def _save(s, obj, conflict_name: str):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, f"the name {conflict_name!r} is already used") from None
    s.refresh(obj)


# ---- metrics & published clients -------------------------------------------------------------

@router.get("/metrics")
def list_metrics(request: Request):
    return [m.model_dump(exclude={"formula"}) for m in _state(request).metrics.metrics]


@router.get("/connections/published")
def published_connections(request: Request):
    st = _state(request)
    with st.store.session() as s:
        rows = (s.query(Connection, func.max(Publication.published_at))
                .join(MappingRun, MappingRun.connection_id == Connection.id)
                .join(Publication, Publication.run_id == MappingRun.id)
                .filter(Publication.schema == st.settings.publish_schema)
                .group_by(Connection.id).order_by(Connection.name).all())
        return [{"id": c.id, "name": c.name, "dialect": c.dialect, "published_at": at.isoformat()} for c, at in rows]


# ---- report templates ---------------------------------------------------------------------------

@router.get("/reports")
def list_reports(request: Request):
    with _state(request).store.session() as s:
        return [{k: v for k, v in _report_out(t).items() if k != "blocks"}
                for t in s.query(ReportTemplate).order_by(ReportTemplate.name)]


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, request: Request):
    st = _state(request)
    _check_report(body, st)
    with st.store.session() as s:
        t = ReportTemplate(name=body.name, description=body.description, blocks=body.blocks)
        s.add(t)
        _save(s, t, body.name)
        return _report_out(t)


@router.get("/reports/{rid}")
def get_report(rid: int, request: Request):
    with _state(request).store.session() as s:
        return _report_out(_get(s, ReportTemplate, rid))


@router.put("/reports/{rid}")
def update_report(rid: int, body: ReportIn, request: Request):
    st = _state(request)
    _check_report(body, st)
    with st.store.session() as s:
        t = _get(s, ReportTemplate, rid)
        t.name, t.description, t.blocks = body.name, body.description, body.blocks
        _save(s, t, body.name)
        return _report_out(t)


@router.delete("/reports/{rid}", status_code=204)
def delete_report(rid: int, request: Request):
    with _state(request).store.session() as s:
        s.delete(_get(s, ReportTemplate, rid))
        s.commit()
    return Response(status_code=204)


# ---- dashboards ----------------------------------------------------------------------------------

@router.get("/dashboards")
def list_dashboards(request: Request):
    with _state(request).store.session() as s:
        return [{k: v for k, v in _dashboard_out(d).items() if k != "tiles"}
                for d in s.query(Dashboard).order_by(Dashboard.name)]


@router.post("/dashboards", status_code=201)
def create_dashboard(body: DashboardIn, request: Request):
    st = _state(request)
    _check_dashboard(body, st)
    with st.store.session() as s:
        d = Dashboard(name=body.name, default_period=body.default_period, tiles=body.tiles)
        s.add(d)
        _save(s, d, body.name)
        return _dashboard_out(d)


@router.get("/dashboards/{did}")
def get_dashboard(did: int, request: Request):
    with _state(request).store.session() as s:
        return _dashboard_out(_get(s, Dashboard, did))


@router.put("/dashboards/{did}")
def update_dashboard(did: int, body: DashboardIn, request: Request):
    st = _state(request)
    _check_dashboard(body, st)
    with st.store.session() as s:
        d = _get(s, Dashboard, did)
        d.name, d.default_period, d.tiles = body.name, body.default_period, body.tiles
        _save(s, d, body.name)
        return _dashboard_out(d)


@router.delete("/dashboards/{did}", status_code=204)
def delete_dashboard(did: int, request: Request):
    with _state(request).store.session() as s:
        s.delete(_get(s, Dashboard, did))
        s.commit()
    return Response(status_code=204)


# ---- rendering -----------------------------------------------------------------------------------

def _render(request: Request, connection_id: int, period_spec: dict, blocks: list[dict]) -> dict:
    st = _state(request)
    with st.store.session() as s:
        conn = _get(s, Connection, connection_id)
        try:
            url = decrypt_url(conn.url_encrypted, st.settings.secret_key)
        except DecryptError as exc:
            raise HTTPException(409, f"{exc}; re-enter the password") from None
        name = conn.name
    try:
        period = resolve_period(period_spec, st.today())
    except PeriodError as exc:
        raise HTTPException(422, str(exc)) from None
    ctx = RenderContext(st.catalog, st.metrics, period, name, schema=st.settings.publish_schema,
                        mask=lambda m: mask_secrets(m, url))
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            c = c.execution_options(isolation_level="AUTOCOMMIT")   # one failing block can't abort the rest
            check_published(c, ctx)
            results = render_blocks(blocks, c, ctx)
    except NotPublished as exc:
        raise HTTPException(409, str(exc)) from None
    except OperationalError as exc:
        raise HTTPException(502, f"cannot reach {name}: {mask_secrets(str(exc.orig), url)}") from None
    finally:
        engine.dispose()
    return {"client": {"id": connection_id, "name": name}, "period": period.as_dict(),
            "generated_at": ctx.generated_at.isoformat(), "blocks": results}


@router.post("/reports/{rid}/render")
def render_report(rid: int, body: RenderIn, request: Request):
    with _state(request).store.session() as s:
        blocks = _get(s, ReportTemplate, rid).blocks
    return _render(request, body.connection_id, body.period, blocks)


@router.post("/dashboards/{did}/render")
def render_dashboard(did: int, body: RenderIn, request: Request):
    with _state(request).store.session() as s:
        blocks = [t["block"] for t in _get(s, Dashboard, did).tiles]
    return _render(request, body.connection_id, body.period, blocks)


@router.post("/render-blocks")
def render_unsaved(body: RenderBlocksIn, request: Request):
    return _render(request, body.connection_id, body.period, body.blocks)
