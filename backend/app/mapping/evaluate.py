"""Mapping evaluation: layer ablation x blind synonym masking, plus end-to-end view check (spec §9).

Run from the repo root (it imports mockdata/):
    .venv/bin/python -m app.mapping.evaluate [--clients client1,client2] [--mask 0,0.5,1.0] [--seeds 1,2,3]
                                   [--layers A,AB,ABC] [--refresh-llm] [--no-llm] [--out docs/eval]
"""
import argparse
import json
import random
import statistics
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

from app.catalog.loader import load_catalog
from app.catalog.models import Catalog
from app.mapping.introspect import introspect
from app.mapping.joins import plan_joins
from app.mapping.matcher.embed import Embedder
from app.mapping.matcher.llm import FileCache, LlmMatcher, OpenAIChatClient
from app.mapping.matcher.pipeline import grain_key_scorer, run_matching
from app.mapping.matcher.rules import effective_synonyms
from app.mapping.names import norm
from app.mapping.profile import profile_columns
from app.mapping.types import FieldMapping, JoinPlan
from app.mapping.viewgen import BASE_VIEW, CALC_VIEW, build_base_select, build_view_ddl, publish
from app.settings import ROOT, Settings
from mockdata.config import CLIENT1_URL, CLIENT2_URL
from mockdata.generate import GOLDEN_PATH
from mockdata.golden import format_value, read_golden
from mockdata.writers import client1_pg, client2_mysql

EVAL_SCHEMA = "lending_rpt_eval"
CLIENTS = {"client1": (CLIENT1_URL, client1_pg), "client2": (CLIENT2_URL, client2_mysql)}
EXPECTED_GRAIN = {"client1": "loan_application", "client2": "TBL_LOAN_APPL"}
LLM_CACHE = ROOT / "eval" / "llm-cache"


def answer_key(writer) -> dict[str, set[tuple[str, str]]]:
    key: dict[str, set[tuple[str, str]]] = {}
    for spec in writer.TABLES:
        for column, field_id in spec.columns.items():
            key.setdefault(field_id, set()).add((spec.name, column))
    return key


def exact_match_synonyms(catalog: Catalog, column_names: list[str]) -> list[tuple[str, str]]:
    """(field_id, synonym) pairs whose synonym equals a column name of the client under test."""
    names = {norm(c) for c in column_names}
    return sorted((f.id, s) for f in catalog.raw_fields for s in f.synonyms if norm(s) in names)


def mask(pairs: list[tuple[str, str]], ratio: float, seed: int) -> set[tuple[str, str]]:
    return set(random.Random(seed).sample(pairs, round(ratio * len(pairs))))


def score_run(mappings: dict[str, FieldMapping], key, plan: JoinPlan, expected_grain: str,
              expected_tables: set[str], catalog: Catalog) -> dict:
    layers = {k: {"decided": 0, "correct": 0} for k in ("A", "B", "C", "key")}
    correct = required_correct = wrong = unmapped = 0
    errors = []
    for f in catalog.raw_fields:
        m = mappings[f.id]
        got = (m.source.table, m.source.column) if m.source else None
        ok = got in key.get(f.id, set()) if got else not key.get(f.id)
        if m.decided_by in layers:
            layers[m.decided_by]["decided"] += 1
            layers[m.decided_by]["correct"] += ok
        correct += ok
        required_correct += ok and f.required_for_mapping
        if not ok:
            if got is None:
                unmapped += 1
            else:
                wrong += 1
            errors.append({"field": f.id, "got": f"{got[0]}.{got[1]}" if got else None,
                           "expected": sorted(f"{t}.{c}" for t, c in key.get(f.id, ())),
                           "decided_by": m.decided_by, "score": round(m.score, 3)})
    joined = {plan.grain.table} | {j.table for j in plan.joins}
    return {
        "field_accuracy": correct / len(catalog.raw_fields),
        "required_accuracy": required_correct / sum(f.required_for_mapping for f in catalog.raw_fields),
        "wrong": wrong, "unmapped": unmapped, "by_layer": layers, "errors": errors,
        "join_plan_correct": plan.grain.table == expected_grain and joined == expected_tables,
    }


def end_to_end(engine, info, plan, mappings, catalog) -> dict:
    """Publish suggestions as-is to lending_rpt_eval and compare every cell with the golden CSV."""
    sources = {fid: m.source for fid, m in mappings.items()}
    try:
        statements = build_view_ddl(info.dialect, EVAL_SCHEMA, build_base_select(info, plan, sources, catalog),
                                    catalog)
        publish(engine, statements, plan.grain, EVAL_SCHEMA)
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT * FROM {EVAL_SCHEMA}.{BASE_VIEW}")).mappings().all()
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        with engine.begin() as conn:     # never leave views behind: they block mockdata --reset
            for v in (CALC_VIEW, BASE_VIEW):
                conn.execute(text(f"DROP VIEW IF EXISTS {EVAL_SCHEMA}.{v}"))
    golden = {r["application_id"]: r for r in read_golden(GOLDEN_PATH)}
    types = {f.id: f.type for f in catalog.raw_fields}
    per_field = {f.id: 0 for f in catalog.raw_fields}
    for r in rows:
        g = golden.get(str(r["application_id"]))
        for fid in per_field:
            per_field[fid] += g is not None and format_value(r[fid], types[fid]) == g[fid]
    n = len(golden)
    return {"ok": True, "rows": len(rows), "cell_match": sum(per_field.values()) / (n * len(per_field)),
            "fields_below_100": {k: round(v / n, 4) for k, v in per_field.items() if v < n}}


def _llm(args, settings) -> LlmMatcher | None:
    if args.no_llm or not settings.openai_api_key:
        return None
    return LlmMatcher(OpenAIChatClient(settings.openai_api_key), settings.llm_model,
                      cache=FileCache(LLM_CACHE), read_cache=not args.refresh_llm)


def run(args) -> dict:
    settings = Settings()
    catalog = load_catalog(settings.catalog_path)
    embedder = Embedder()
    llm = _llm(args, settings)
    layer_sets = [l for l in args.layers if l != "ABC" or llm is not None]
    skipped_abc = "ABC" in args.layers and llm is None
    out = {"date": date.today().isoformat(), "model": settings.llm_model if llm else None,
           "embedding_model": "BAAI/bge-small-en-v1.5", "b_accept": settings.b_accept,
           "b_margin": settings.b_margin, "catalog_version": catalog.version, "abc_skipped": skipped_abc,
           "runs": [], "end_to_end": [], "exact_match_synonyms": {}}

    for client in args.clients:
        url, writer = CLIENTS[client]
        engine = create_engine(url)
        try:
            info = introspect(engine, [writer.SCHEMA])
            profiles = profile_columns(engine, info, catalog)
            key = answer_key(writer)
            expected_tables = {s.name for s in writer.TABLES}
            expected_grain = EXPECTED_GRAIN[client]
            pairs = exact_match_synonyms(catalog, [p.ref.column for p in profiles])
            out["exact_match_synonyms"][client] = len(pairs)
            for ratio in args.mask:
                seeds = args.seeds if 0 < ratio < 1 else args.seeds[:1]
                for seed in seeds:
                    synonyms = effective_synonyms(catalog, mask(pairs, ratio, seed))
                    for layers in layer_sets:
                        emb = embedder if "B" in layers else None
                        plan = plan_joins(info, profiles, grain_key_scorer(profiles, catalog, synonyms, emb))
                        result = run_matching(profiles, plan, catalog, layers, synonyms, emb,
                                              llm if "C" in layers else None, settings.b_accept, settings.b_margin)
                        metrics = score_run(result.mappings, key, plan, expected_grain, expected_tables, catalog)
                        out["runs"].append({"client": client, "mask": ratio, "seed": seed, "layers": layers,
                                            "llm_calls": result.llm_calls, "llm_tokens": result.llm_tokens,
                                            **metrics})
                        print(f"{client} mask={ratio:.0%} seed={seed} {layers:3s} "
                              f"fields={metrics['field_accuracy']:.1%} required={metrics['required_accuracy']:.1%}",
                              file=sys.stderr)
                        if seed == seeds[0] and layers == layer_sets[-1]:
                            e2e = end_to_end(engine, info, plan, result.mappings, catalog)
                            out["end_to_end"].append({"client": client, "mask": ratio, "layers": layers, **e2e})
        finally:
            engine.dispose()
    return out


def _summary_rows(runs: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in runs:
        groups.setdefault((r["client"], r["mask"], r["layers"]), []).append(r)
    rows = []
    for (client, ratio, layers), rs in groups.items():
        mean = lambda k: statistics.mean(r[k] for r in rs)
        rows.append({"client": client, "mask": ratio, "layers": layers, "n": len(rs),
                     "field_accuracy": mean("field_accuracy"), "required_accuracy": mean("required_accuracy"),
                     "wrong": mean("wrong"), "unmapped": mean("unmapped"),
                     "decided": {k: mean_layer(rs, k) for k in ("A", "B", "C")},
                     "llm_calls": mean("llm_calls"), "llm_tokens": mean("llm_tokens")})
    return rows


def mean_layer(rs: list[dict], layer: str) -> float:
    return statistics.mean(r["by_layer"][layer]["decided"] for r in rs)


def render_markdown(data: dict) -> str:
    lines = [f"# Mapping evaluation — {data['date']}", "",
             f"- Embedding model: `{data['embedding_model']}`; Layer B accepts at ≥ {data['b_accept']} "
             f"with margin ≥ {data['b_margin']}.",
             f"- LLM: `{data['model']}`" if data["model"] else "- LLM: none",
             f"- Exact-match synonyms available to Layer A: "
             + ", ".join(f"{c} {n}" for c, n in data["exact_match_synonyms"].items()) + ".",
             "- Masking hides that share of the exact-match synonyms (from both A and B); 50% is averaged "
             "over the seeds given. Columns named exactly like a field ID (most of client1) are not "
             "synonyms and cannot be masked, so Layer A still decides them at 100%.", ""]
    if data["abc_skipped"]:
        lines += ["> **ABC skipped:** no OpenAI key (or `--no-llm`); only layers A and AB were run.", ""]
    lines += ["## Accuracy", "",
              "| Client | Masked | Layers | Fields (of 59) | Required (of 16) | Wrong | Unmapped | "
              "Decided A / B / C | LLM calls |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in _summary_rows(data["runs"]):
        d = r["decided"]
        lines.append(f"| {r['client']} | {r['mask']:.0%} | {r['layers']} | {r['field_accuracy']:.1%} | "
                     f"{r['required_accuracy']:.1%} | {r['wrong']:g} | {r['unmapped']:g} | "
                     f"{d['A']:g} / {d['B']:g} / {d['C']:g} | {r['llm_calls']:g} |")
    lines += ["", "## Errors at the hardest setting", ""]
    for client in dict.fromkeys(r["client"] for r in data["runs"]):
        hardest = max((r for r in data["runs"] if r["client"] == client),
                      key=lambda r: (r["mask"], len(r["layers"]), -r["seed"]))
        lines.append(f"**{client}**, {hardest['mask']:.0%} masked, layers {hardest['layers']}, "
                     f"seed {hardest['seed']}: {len(hardest['errors'])} errors")
        lines.append("")
        for e in hardest["errors"]:
            lines.append(f"- `{e['field']}`: got `{e['got']}` (by {e['decided_by']}, {e['score']}), "
                         f"expected {', '.join(f'`{x}`' for x in e['expected'])}")
        lines.append("")
    lines += ["## End to end (suggestions accepted unchanged, published to `lending_rpt_eval`)", "",
              "| Client | Masked | Layers | Result |", "|---|---|---|---|"]
    for e in data["end_to_end"]:
        if e["ok"]:
            below = ", ".join(f"`{k}` {v:.0%}" for k, v in e["fields_below_100"].items()) or "none"
            res = f"{e['cell_match']:.2%} of cells match golden; fields below 100%: {below}"
        else:
            res = f"publish failed: {e['error']}"
        lines.append(f"| {e['client']} | {e['mask']:.0%} | {e['layers']} | {res} |")
    lines += ["", "## Threats to validity", "",
              "- **Abbreviation list bias.** Layer B expands abbreviations with a fixed list written "
              "knowing Client 2's naming. The blind test measures loss of synonyms, not handling of "
              "unfamiliar abbreviations.",
              "- **Tuned on the test clients.** Layer B's column-text layout was chosen by measuring "
              "accuracy on these same two clients.",
              "- **Two synthetic clients.** Both share value formats (L1/L2 only); real schemas will be harder.",
              "- **Cached LLM responses.** Re-runs reuse `eval/llm-cache/`; use `--refresh-llm` for fresh "
              "answers. Temperature 0 does not guarantee identical answers across model versions.", ""]
    return "\n".join(lines)


def parse_args(argv):
    p = argparse.ArgumentParser(description="Evaluate mapping quality against the mock clients' answer key.")
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
    p.add_argument("--clients", type=split, default=["client1", "client2"])
    p.add_argument("--mask", type=lambda s: [float(x) for x in split(s)], default=[0.0, 0.5, 1.0])
    p.add_argument("--seeds", type=lambda s: [int(x) for x in split(s)], default=[1, 2, 3])
    p.add_argument("--layers", type=split, default=["A", "AB", "ABC"])
    p.add_argument("--refresh-llm", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--out", type=Path, default=ROOT / "docs" / "eval")
    args = p.parse_args(argv)
    for c in args.clients:
        if c not in CLIENTS:
            p.error(f"unknown client {c!r}")
    for l in args.layers:
        if l not in ("A", "AB", "ABC"):
            p.error(f"unknown layers {l!r}")
    return args


def main(argv=None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not GOLDEN_PATH.exists():
        sys.exit("golden CSV missing; run: python -m mockdata.generate --reset")
    data = run(args)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"{data['date']}-mapping-eval"
    stem.with_suffix(".json").write_text(json.dumps(data, indent=2))
    report = render_markdown(data)
    stem.with_suffix(".md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
