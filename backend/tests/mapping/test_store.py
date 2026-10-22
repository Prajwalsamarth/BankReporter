from app.store import Connection, MappingEntry, MappingRun, Publication, Store


def test_store_round_trip(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'app.sqlite'}")
    with store.session() as s:
        conn = Connection(name="NovaBank", dialect="postgresql", url_encrypted="tok", schemas=["los"])
        s.add(conn)
        s.flush()
        run = MappingRun(connection_id=conn.id, catalog_version=1, layers="ABC", status="running",
                         join_plan={"grain": None}, profiles=[], warnings=["llm_disabled"])
        s.add(run)
        s.flush()
        s.add(MappingEntry(run_id=run.id, field_id="cibil_score", source_schema="los",
                           source_table="bureau_report", source_column="cibil_score", score=1.0,
                           decided_by="A", reason="r", warnings=[], candidates=[], status="suggested"))
        s.add(Publication(run_id=run.id, schema="lending_rpt", ddl="CREATE VIEW ...", row_count=2000))
        s.commit()
        run_id = run.id

    with store.session() as s:
        run = s.get(MappingRun, run_id)
        assert run.connection.name == "NovaBank"
        assert run.warnings == ["llm_disabled"]
        assert run.join_plan_confirmed is False
        assert [e.field_id for e in run.entries] == ["cibil_score"]
        assert run.publications[0].row_count == 2000


def test_store_creates_parent_directory(tmp_path):
    Store(f"sqlite:///{tmp_path / 'nested' / 'dir' / 'app.sqlite'}")
    assert (tmp_path / "nested" / "dir").is_dir()


def test_deleting_connection_deletes_runs(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'app.sqlite'}")
    with store.session() as s:
        conn = Connection(name="x", dialect="mysql", url_encrypted="t", schemas=[])
        s.add(conn)
        s.flush()
        s.add(MappingRun(connection_id=conn.id, catalog_version=1, layers="A", status="ready"))
        s.commit()
        s.delete(conn)
        s.commit()
        assert s.query(MappingRun).count() == 0
