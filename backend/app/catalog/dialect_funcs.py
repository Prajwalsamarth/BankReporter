"""SQL functions whose spelling differs per dialect (spec §4.2).

Each is a FunctionElement with a @compiles override per supported dialect;
any other dialect raises UnsupportedDialect.
"""
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import Date, Integer

SUPPORTED = ("postgresql", "mysql", "sqlite")


class UnsupportedDialect(Exception):
    pass


class _DialectFunction(FunctionElement):
    inherit_cache = True


class Least(_DialectFunction):
    name = "least"
    inherit_cache = True


class Greatest(_DialectFunction):
    name = "greatest"
    inherit_cache = True


@compiles(Least)
@compiles(Greatest)
def _least_greatest(element, compiler, **kw):
    name = element.name
    if compiler.dialect.name == "sqlite":
        name = "min" if name == "least" else "max"
    elif compiler.dialect.name not in SUPPORTED:
        raise UnsupportedDialect(f"{element.name.upper()} not supported on {compiler.dialect.name}")
    return f"{name}({compiler.process(element.clauses, **kw)})"
