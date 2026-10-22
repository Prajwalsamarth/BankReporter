# Mapping difficulty levels

The two mock clients differ from each other, and from the canonical catalog, only in **naming (L1)** and **structure (L2)**. This guide explains how to make Client 2 harder, one level at a time, and what the Part 2 matcher must be able to do at each level.

Each level adds to the ones before it. To introduce a level:

1. Change `mockdata/ddl/client2_mysql.sql`.
2. Change `mockdata/writers/client2_mysql.py`. Its `TableSpec.columns` maps a client column to a canonical field. Levels 3 and 4 also need a transform applied when writing.
3. Keep the golden CSV **canonical**. It must not change, because it's the answer the mapping has to reproduce.
4. Add a readback test in `backend/tests/mockdata/test_writers.py` that applies the inverse transform. This proves the writer is still faithful.

---

## L1 — Naming *(built)*

**In Client 2:** cryptic upper-case abbreviations such as `CIB_SCR`, `NET_MTH_INC` and `WO_FLG`.

**Matcher needs:** to compare client column names against each catalog field's `id`, `label`, `synonyms` and `description`, using token similarity (split on `_` and expand abbreviations: `MTH→monthly`, `INC→income`, `AMT→amount`), plus exact synonym hits. Most Client 2 columns appear in the catalog `synonyms` in lower case, so exact synonym matching sets the baseline score. The interesting test is how well it does once synonyms are removed.

## L2 — Structure *(built)*

**In Client 2:** three wide tables with no declared foreign keys. They join on `APPL_NO` by name only.

**In Client 1:** eight normalised tables with declared FKs, and a one-to-many `customer` → `loan_application` link.

**Matcher needs:**
- Join-path inference. Use declared FKs where they exist. Otherwise, look for columns with the same name or an `_id`/`_no` suffix that are unique on one side.
- Choosing the **grain table**, the one whose primary key maps to `application_id`.
- `LEFT JOIN`s from the grain table, because decision and disbursement rows exist only for some applications.

---

## L3 — Representation *(documented, not built)*

| Change in Client 2 | Writer transform (canonical → client) | Matcher needs (client → canonical) |
|---|---|---|
| `LN_AMT_REQ` → `LN_AMT_REQ_LAKH DECIMAL(8,4)` (amount in lakhs) | `amount / 100000` | Unit detection from the column name (`LAKH`, `CR`, `PAISE`) or the value range; a **scale transform** `× 100000` |
| `GNDR` stored as `1/2/3` | `{MALE:1, FEMALE:2, OTHER:3}` | **Value mapping**: sample distinct values and propose a code → enum mapping for the user to confirm |
| `APPL_DT`, `CUST_DOB` as `VARCHAR(10)` `'DD/MM/YYYY'` | `strftime('%d/%m/%Y')` | **Date parse transform** with format detection from sampled values; dialect-specific SQL (`STR_TO_DATE` on MySQL, `to_date` on PG) |
| `APPL_STS` as an integer FK to a new `MST_STATUS(STS_ID, STS_DESC)` | lookup ID | **Lookup join**: find that the code column joins a small master table, and map its description column instead |
| `WO_FLG` as `'Y'/'N'` | `'Y' if v else 'N'` | Boolean value mapping |

Part 2's mapping model would gain a `transform` on each mapping: `scale(factor)`, `value_map({...})`, `parse_date(fmt)`, `lookup(table, key, value)`. Each compiles to a SQLAlchemy expression in the base view.

## L4 — Split / merge *(documented, not built)*

| Change in Client 2 | Writer transform | Matcher needs |
|---|---|---|
| `CUST_NM` → `CUST_FNAME`, `CUST_MNAME`, `CUST_LNAME` | split on spaces | **Many-to-one concat** transform: `CONCAT_WS(' ', f, m, l)` |
| `NET_MTH_INC` → `NET_ANN_INC` (annual only) | `× 12` | **Derived-unit** transform: `/ 12`, detected from `ANN`/`YR` tokens |
| `BR_CD` and `PIN_CD` merged into `LOC_CD = BR_CD || '-' || PIN_CD` | concat | **One-to-many split** transform (`SUBSTRING_INDEX` / `split_part`) |

## L5 — Missing / extra *(documented, not built)*

| Change in Client 2 | Matcher needs |
|---|---|
| Drop `CKYC_NO` and `EMPLR_NM` | A **coverage report**: catalog fields with no source column. The view emits `NULL` for them. Block "mapping complete" only when a missing field is `required_for_mapping`. |
| Add `CRTD_BY`, `LST_UPD_TS`, `BATCH_ID`, `ETL_RUN_ID` | An **ignore list** and a confidence threshold, so audit or ETL columns aren't force-matched to the nearest catalog field. |
| Add `CIB_SCR_V2` next to `CIB_SCR` | **Ambiguity handling**: two strong candidates for one field. Ask the user, and remember the choice. |

---

## Suggested order to build them

1. **L5** first. It needs no transforms, and coverage reporting is needed anyway.
2. **L3** value mapping and scale. These are the most common in real bank data.
3. **L3** date parsing and lookup joins.
4. **L4**.
