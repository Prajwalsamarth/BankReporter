"""The app's own SQLite storage. Holds configuration and mapping metadata, never client rows."""
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, ForeignKey, String, create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Connection(Base):
    __tablename__ = "connection"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    dialect: Mapped[str] = mapped_column(String(20))
    url_encrypted: Mapped[str]
    schemas: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
    runs: Mapped[list["MappingRun"]] = relationship(back_populates="connection", cascade="all, delete-orphan")


class MappingRun(Base):
    __tablename__ = "mapping_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("connection.id"))
    catalog_version: Mapped[int]
    layers: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(12))        # running | ready | failed | published
    join_plan: Mapped[dict | None] = mapped_column(JSON, default=None)
    join_plan_confirmed: Mapped[bool] = mapped_column(default=False)
    profiles: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(default=None)
    llm_calls: Mapped[int] = mapped_column(default=0)
    llm_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    connection: Mapped[Connection] = relationship(back_populates="runs")
    entries: Mapped[list["MappingEntry"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="MappingEntry.position")
    publications: Mapped[list["Publication"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class MappingEntry(Base):
    __tablename__ = "mapping_entry"
    run_id: Mapped[int] = mapped_column(ForeignKey("mapping_run.id"), primary_key=True)
    field_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(default=0)        # catalog order
    source_schema: Mapped[str | None] = mapped_column(default=None)
    source_table: Mapped[str | None] = mapped_column(default=None)
    source_column: Mapped[str | None] = mapped_column(default=None)
    score: Mapped[float] = mapped_column(default=0.0)
    decided_by: Mapped[str] = mapped_column(String(4), default="none")
    reason: Mapped[str] = mapped_column(default="")
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="unmapped")
    suggestion: Mapped[dict] = mapped_column(JSON, default=dict)   # the matcher's original answer, for reset
    run: Mapped[MappingRun] = relationship(back_populates="entries")


class Publication(Base):
    __tablename__ = "publication"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("mapping_run.id"))
    schema: Mapped[str] = mapped_column(String(64))
    ddl: Mapped[str]
    row_count: Mapped[int]
    published_at: Mapped[datetime] = mapped_column(default=_now)
    run: Mapped[MappingRun] = relationship(back_populates="publications")


class Store:
    def __init__(self, url: str):
        database = make_url(url).database
        if database and database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self):
        with self._sessions() as s:
            yield s
