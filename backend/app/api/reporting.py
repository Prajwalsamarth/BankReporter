# backend/app/api/reporting.py
"""Reporting & dashboards API (spec §7); ownership and client scoping from Part 4."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, or_
from sqlalchemy.exc import OperationalError

from app.auth.access import CHOOSE_CLIENT, check_editable, is_editable, scope_connection, visible_item
from app.auth.scope import Scope, get_scope
from app.connections import DecryptError, decrypt_url, mask_secrets
from app.reporting.period import PeriodError, resolve_period
from app.reporting.render import NotPublished, RenderContext, check_published, render_blocks
from app.reporting.spec import check_blocks
from app.store import Dashboard, ReportTemplate

router = APIRouter(prefix="/api")
TILE_TYPES = {"kpi", "chart", "table"}
WIDTHS = (3, 4, 6, 8, 12)
HEIGHTS = ("s", "m", "l")


class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    blocks: list[dict]
    shared: bool = True          # admin only; client users always create private items


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    default_period: dict = Field(default_factory=lambda: {"preset": "last_month"})
    tiles: list[dict]
    shared: bool = True


class RenderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")      # an old client sending connection_id fails loudly
    period: dict


class RenderBlocksIn(RenderIn):
    blocks: list[dict]


def _state(request: Request):
    return request.app.state


def _ownership(obj, scope: Scope) -> dict:
    return {"shared": obj.client_id is None, "editable": is_editable(scope, obj),
            "owner": {"id": obj.client.id, "name": obj.client.name} if obj.client else None}


def _report_out(t: ReportTemplate, scope: Scope) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description, "blocks": t.blocks,
            "updated_at": t.updated_at.isoformat(), **_ownership(t, scope)}


def _dashboard_out(d: Dashboard, scope: Scope) -> dict:
    return {"id": d.id, "name": d.name, "default_period": d.default_period, "tiles": d.tiles,
            "updated_at": d.updated_at.isoformat(), **_ownership(d, scope)}


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


def _visible_query(s, model, scope: Scope):
    q = s.query(model).order_by(model.name)
    if not scope.is_admin:
        q = q.filter(or_(model.client_id.is_(None), model.client_id == scope.client_id))
    return q


def _new_owner(scope: Scope, shared: bool) -> int | None:
    if not scope.is_admin:
        return scope.client_id
    if shared:
        return None
    if scope.client_id is None:
        raise HTTPException(409, CHOOSE_CLIENT)
    return scope.client_id


def _check_name(s, model, name: str, owner: int | None, exclude: int | None = None) -> None:
    """Names are unique per owner, and a private item can't reuse a shared item's name (spec §2.2)."""
    clash = s.query(model).filter(model.name == name, model.id != (exclude or 0))
    same_owner = model.client_id.is_(None) if owner is None else model.client_id == owner
    if clash.filter(same_owner).first() or (owner is not None and clash.filter(model.client_id.is_(None)).first()):
        raise HTTPException(409, f"the name {name!r} is already used")


def _commit(s, obj) -> None:
    s.commit()
    s.refresh(obj)


# ---- metrics -------------------------------------------------------------------------------------

@router.get("/metrics")
def list_metrics(request: Request):
    return [m.model_dump(exclude={"formula"}) for m in _state(request).metrics.metrics]


# ---- report templates ---------------------------------------------------------------------------

@router.get("/reports")
def list_reports(request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        return [{k: v for k, v in _report_out(t, scope).items() if k != "blocks"}
                for t in _visible_query(s, ReportTemplate, scope)]


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, request: Request, scope: Scope = Depends(get_scope)):
    st = _state(request)
    _check_report(body, st)
    owner = _new_owner(scope, body.shared)
    with st.store.session() as s:
        _check_name(s, ReportTemplate, body.name, owner)
        t = ReportTemplate(name=body.name, description=body.description, blocks=body.blocks, client_id=owner)
        s.add(t)
        _commit(s, t)
        return _report_out(t, scope)


@router.get("/reports/{rid}")
def get_report(rid: int, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        return _report_out(visible_item(s, scope, ReportTemplate, rid), scope)


@router.put("/reports/{rid}")
def update_report(rid: int, body: ReportIn, request: Request, scope: Scope = Depends(get_scope)):
    st = _state(request)
    with st.store.session() as s:
        t = visible_item(s, scope, ReportTemplate, rid)
        check_editable(scope, t)
        _check_report(body, st)
        _check_name(s, ReportTemplate, body.name, t.client_id, exclude=t.id)
        t.name, t.description, t.blocks = body.name, body.description, body.blocks
        _commit(s, t)
        return _report_out(t, scope)


@router.delete("/reports/{rid}", status_code=204)
def delete_report(rid: int, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        t = visible_item(s, scope, ReportTemplate, rid)
        check_editable(scope, t)
        s.delete(t)
        s.commit()
    return Response(status_code=204)


# ---- dashboards ----------------------------------------------------------------------------------

@router.get("/dashboards")
def list_dashboards(request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        return [{k: v for k, v in _dashboard_out(d, scope).items() if k != "tiles"}
                for d in _visible_query(s, Dashboard, scope)]


@router.post("/dashboards", status_code=201)
def create_dashboard(body: DashboardIn, request: Request, scope: Scope = Depends(get_scope)):
    st = _state(request)
    _check_dashboard(body, st)
    owner = _new_owner(scope, body.shared)
    with st.store.session() as s:
        _check_name(s, Dashboard, body.name, owner)
        d = Dashboard(name=body.name, default_period=body.default_period, tiles=body.tiles, client_id=owner)
        s.add(d)
        _commit(s, d)
        return _dashboard_out(d, scope)


@router.get("/dashboards/{did}")
def get_dashboard(did: int, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        return _dashboard_out(visible_item(s, scope, Dashboard, did), scope)


@router.put("/dashboards/{did}")
def update_dashboard(did: int, body: DashboardIn, request: Request, scope: Scope = Depends(get_scope)):
    st = _state(request)
    with st.store.session() as s:
        d = visible_item(s, scope, Dashboard, did)
        check_editable(scope, d)
        _check_dashboard(body, st)
        _check_name(s, Dashboard, body.name, d.client_id, exclude=d.id)
        d.name, d.default_period, d.tiles = body.name, body.default_period, body.tiles
        _commit(s, d)
        return _dashboard_out(d, scope)


@router.delete("/dashboards/{did}", status_code=204)
def delete_dashboard(did: int, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        d = visible_item(s, scope, Dashboard, did)
        check_editable(scope, d)
        s.delete(d)
        s.commit()
    return Response(status_code=204)


# ---- rendering -----------------------------------------------------------------------------------

def _render(request: Request, scope: Scope, period_spec: dict, blocks: list[dict]) -> dict:
    st = _state(request)
    with st.store.session() as s:
        conn = scope_connection(s, scope)
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
    # client.id is the scope's client, so a tab whose header shows another client can spot the switch
    return {"client": {"id": scope.client_id, "name": name}, "period": period.as_dict(),
            "generated_at": ctx.generated_at.isoformat(), "blocks": results}


@router.post("/reports/{rid}/render")
def render_report(rid: int, body: RenderIn, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        blocks = visible_item(s, scope, ReportTemplate, rid).blocks
    return _render(request, scope, body.period, blocks)


@router.post("/dashboards/{did}/render")
def render_dashboard(did: int, body: RenderIn, request: Request, scope: Scope = Depends(get_scope)):
    with _state(request).store.session() as s:
        blocks = [t["block"] for t in visible_item(s, scope, Dashboard, did).tiles]
    return _render(request, scope, body.period, blocks)


@router.post("/render-blocks")
def render_unsaved(body: RenderBlocksIn, request: Request, scope: Scope = Depends(get_scope)):
    return _render(request, scope, body.period, body.blocks)
