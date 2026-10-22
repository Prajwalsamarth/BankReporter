# Mapping evaluation — 2026-10-22

- Embedding model: `BAAI/bge-small-en-v1.5`; Layer B accepts at ≥ 0.85 with margin ≥ 0.05.
- LLM: none
- Exact-match synonyms available to Layer A: client1 16, client2 58.
- Masking hides that share of the exact-match synonyms (from both A and B); 50% is averaged over the seeds given. Columns named exactly like a field ID (most of client1) are not synonyms and cannot be masked, so Layer A still decides them at 100%.

> **ABC skipped:** no OpenAI key (or `--no-llm`); only layers A and AB were run.

## Accuracy

| Client | Masked | Layers | Fields (of 59) | Required (of 16) | Wrong | Unmapped | Decided A / B / C | LLM calls |
|---|---|---|---|---|---|---|---|---|
| client1 | 0% | A | 100.0% | 100.0% | 0 | 0 | 58 / 0 / 0 | 0 |
| client1 | 0% | AB | 100.0% | 100.0% | 0 | 0 | 58 / 0 / 0 | 0 |
| client1 | 50% | A | 86.4% | 81.2% | 0 | 8 | 50 / 0 / 0 | 0 |
| client1 | 50% | AB | 100.0% | 100.0% | 0 | 0 | 50 / 8 / 0 | 0 |
| client1 | 100% | A | 72.9% | 68.8% | 0 | 16 | 42 / 0 / 0 | 0 |
| client1 | 100% | AB | 100.0% | 100.0% | 0 | 0 | 42 / 16 / 0 | 0 |
| client2 | 0% | A | 100.0% | 100.0% | 0 | 0 | 58 / 0 / 0 | 0 |
| client2 | 0% | AB | 100.0% | 100.0% | 0 | 0 | 58 / 0 / 0 | 0 |
| client2 | 50% | A | 52.0% | 62.5% | 0 | 28.3333 | 29.6667 / 0 / 0 | 0 |
| client2 | 50% | AB | 100.0% | 100.0% | 0 | 0 | 29.6667 / 28.3333 / 0 | 0 |
| client2 | 100% | A | 3.4% | 6.2% | 0 | 57 | 1 / 0 / 0 | 0 |
| client2 | 100% | AB | 100.0% | 100.0% | 0 | 0 | 1 / 57 / 0 | 0 |

## Errors at the hardest setting

**client1**, 100% masked, layers AB, seed 1: 0 errors


**client2**, 100% masked, layers AB, seed 1: 0 errors


## End to end (suggestions accepted unchanged, published to `lending_rpt_eval`)

| Client | Masked | Layers | Result |
|---|---|---|---|
| client1 | 0% | AB | 100.00% of cells match golden; fields below 100%: none |
| client1 | 50% | AB | 100.00% of cells match golden; fields below 100%: none |
| client1 | 100% | AB | 100.00% of cells match golden; fields below 100%: none |
| client2 | 0% | AB | 100.00% of cells match golden; fields below 100%: none |
| client2 | 50% | AB | 100.00% of cells match golden; fields below 100%: none |
| client2 | 100% | AB | 100.00% of cells match golden; fields below 100%: none |

## Threats to validity

- **Abbreviation list bias.** Layer B expands abbreviations with a fixed list written knowing Client 2's naming. The blind test measures loss of synonyms, not handling of unfamiliar abbreviations.
- **Tuned on the test clients.** Layer B's column-text layout was chosen by measuring accuracy on these same two clients.
- **Two synthetic clients.** Both share value formats (L1/L2 only); real schemas will be harder.
- **Cached LLM responses.** Re-runs reuse `eval/llm-cache/`; use `--refresh-llm` for fresh answers. Temperature 0 does not guarantee identical answers across model versions.
