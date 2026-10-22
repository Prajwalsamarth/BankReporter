import re

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm(name: str) -> str:
    """Lower-case, split camelCase, and join words with '_' (NetMthInc -> net_mth_inc)."""
    return _NON_ALNUM.sub("_", _CAMEL.sub("_", name.strip()).lower()).strip("_")
