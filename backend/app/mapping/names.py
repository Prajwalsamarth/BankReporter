import re

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm(name: str) -> str:
    """Lower-case, split camelCase, and join words with '_' (NetMthInc -> net_mth_inc).

    All-caps names are not camel-split, so DPD30_12M stays dpd30_12m.
    """
    name = name.strip()
    if any(ch.islower() for ch in name):
        name = _CAMEL.sub("_", name)
    return _NON_ALNUM.sub("_", name.lower()).strip("_")
