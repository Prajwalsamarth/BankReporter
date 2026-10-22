# backend/app/reporting/defaults.py
"""Ready-made report templates and dashboards (spec §6), added as shared items when missing by name."""
from pathlib import Path

import yaml

from app.store import Dashboard, ReportTemplate


def seed_defaults(store, directory: Path) -> None:
    for path in sorted(Path(directory).glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        with store.session() as s:
            if doc["kind"] == "report" and not s.query(ReportTemplate).filter_by(name=doc["name"], client_id=None).first():
                s.add(ReportTemplate(name=doc["name"], description=doc.get("description", ""), blocks=doc["blocks"]))
            elif doc["kind"] == "dashboard" and not s.query(Dashboard).filter_by(name=doc["name"], client_id=None).first():
                s.add(Dashboard(name=doc["name"], default_period=doc.get("default_period", {"preset": "last_month"}),
                                tiles=doc["tiles"]))
            s.commit()
