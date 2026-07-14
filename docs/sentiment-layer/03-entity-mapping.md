# Entity → MASI Symbol Mapping (A4)

Maps `company_specific`-topic article text to a MASI ticker so the article
can be scored against the `symbol:{TICKER}` subject key. This is a French
(and secondarily English) alias-matching problem, not an NLP/NER problem —
Moroccan financial media use a small, stable vocabulary of company names and
abbreviations, and a curated alias table is more auditable and cheaper than
a trained entity linker.

## `masi_aliases.json`

`data/masi_aliases.json` — one entry per MASI-listed company, keyed by
ticker:

```json
{
  "ATW": {
    "isin": "MA0000011926",
    "aliases": ["Attijariwafa Bank", "Attijariwafa", "AWB", "Attijari"]
  },
  "IAM": {
    "isin": "MA0000011403",
    "aliases": ["Maroc Telecom", "Itissalat Al-Maghrib", "IAM"]
  },
  "BCP": {
    "isin": "MA0000011114",
    "aliases": ["Banque Centrale Populaire", "BCP", "Groupe BCP", "Banque Populaire"]
  },
  "LBV": {
    "isin": "MA0000012049",
    "aliases": ["Label'Vie", "Label Vie", "Carrefour Maroc"]
  },
  "TQM": {
    "isin": "MA0000011882",
    "aliases": ["Taqa Morocco", "TAQA Morocco", "Jorf Lasfar Energy Company"]
  },
  "GAZ": {
    "isin": "MA0000010546",
    "aliases": ["Afriquia Gaz", "Afriquia"]
  },
  "ADH": {
    "isin": "MA0000011452",
    "aliases": ["Douja Promotion Addoha", "Addoha", "Groupe Addoha"]
  },
  "MNG": {
    "isin": "MA0000011346",
    "aliases": ["Managem", "Groupe Managem"]
  },
  "CIH": {
    "isin": "MA0000010942",
    "aliases": ["CIH Bank", "Crédit Immobilier et Hôtelier"]
  },
  "BOA": {
    "isin": "MA0000011270",
    "aliases": ["Bank of Africa", "BMCE Bank of Africa", "BMCE"]
  }
}
```

`aliases` are the human-curated French (and common abbreviation) forms a
Moroccan financial journalist actually writes — deliberately *not*
auto-generated from `display_name` alone, since real usage diverges from
the canonical registry name (e.g. "BMCE" for Bank of Africa, "AWB" for
Attijariwafa). `isin` enables a second, higher-precision match path.

### Seeding

`scripts/seed_masi_aliases.py` — reads `StockMaster`
(`services/api/app/models.py:447`, fields `symbol`, `display_name`, `isin`)
for every `is_active=True` row with `market_region='masi'`, and writes a
starter `data/masi_aliases.json` with `aliases: [display_name]` (a
single-entry list seeded from the registry's own display name) for any
ticker not already present in the file. This is a one-time/rerunnable
bootstrap, not a live sync — it never overwrites an existing ticker's
human-curated `aliases` list, only adds new tickers with a minimal
single-alias starter entry. A human then edits the file to add the
additional French/abbreviation forms (as in the 10 examples above) before
A4's matching goes live; the script's job is only to guarantee no active
MASI stock is missing an entry, not to guess good aliases.

## Matching rules

`core/quant_core/newsflow/entity_map.py::map_entities(text: str) ->
list[EntityMatch]`:

1. **Normalization**: lowercase, strip accents (NFKD decompose + drop
   combining marks — handles `é`/`è`/`à` etc. so "Crédit" matches "credit"),
   collapse whitespace.
2. **ISIN exact match**: if the normalized text contains a 12-character
   ISIN-shaped token matching `data/masi_aliases.json[*].isin` exactly, that
   is an automatic match with `match_confidence=1.0` (ISINs are
   unambiguous and appear verbatim in some AMMC/exchange filings).
3. **Alias word-boundary match**: for each ticker's alias list, each alias
   is itself normalized (accent-stripped, lowercased) and matched against
   the normalized text with a **word-boundary regex**
   (`\b{re.escape(alias)}\b`, so "AWB" doesn't match inside a longer token,
   and "BCP" doesn't match "OBCPX"). Multi-word aliases (e.g. "Banque
   Centrale Populaire") match as a single boundary-delimited phrase, not
   word-by-word — avoids false positives from three common French words
   appearing near each other unrelatedly.
4. **`match_confidence`**: `1.0` for ISIN match; `0.9` for a full-name alias
   match (e.g. "Attijariwafa Bank"); `0.6` for a short-abbreviation alias
   match (aliases ≤ 4 characters, e.g. "AWB", "IAM", "BCP" — these carry
   higher false-positive risk, most obviously against common words or other
   tickers' substrings, so they're flagged with lower confidence rather
   than dropped; downstream aggregation in
   [04-aggregation-and-factors.md](04-aggregation-and-factors.md) can weight
   or threshold on this).
5. A single article can match multiple tickers (e.g. a merger/acquisition
   story) — `map_entities` returns all matches, not just the highest-
   confidence one; each becomes its own `symbol:{TICKER}` subject candidate
   for A3's LLM scoring pass to confirm/score independently.

## Where matching is applied

- **At ingest**: every writer feeding `persist.py::persist_items()`
  (GDELT, Morocco scrapers, RSS, yfinance news —
  [01-data-sources.md](01-data-sources.md)) calls `map_entities()` on the
  article title + lead paragraph (not full body — title/lead carries almost
  all of the signal and keeps this cheap) and stores the resulting ticker
  list into `alt_news_item.symbols` (JSONB). This is what powers A3's
  batching priority (`symbol-mapped` articles first —
  [02-llm-scoring.md](02-llm-scoring.md)) and lets `symbol:*` subject
  candidates exist even before LLM scoring confirms them.
- **Re-runnable remap task**: `services/worker/tasks/remap_news_entities.py`
  — re-applies `map_entities()` against already-ingested
  `alt_news_item.title`/lead text and overwrites `symbols`, for the case
  where `data/masi_aliases.json` is edited after articles were already
  ingested (a new alias added, a false-positive alias removed). Idempotent,
  safe to run over the full history or a date-bounded slice
  (`remap_news_entities(start_date=None, end_date=None)`). Does **not**
  retroactively re-score already-scored `alt_news_score` rows — a remap
  only changes which future/unscored articles get a `symbol:*` candidate;
  re-scoring is a separate, explicit operational action if ever needed.

## Files

- `data/masi_aliases.json`
- `scripts/seed_masi_aliases.py`
- `core/quant_core/newsflow/entity_map.py`
- `services/worker/tasks/remap_news_entities.py`

## Tests

`core/tests/test_entity_map.py` — accent-stripping, word-boundary
false-positive avoidance (e.g. "BCP" not matching inside an unrelated
longer word), multi-match articles, ISIN exact match, confidence tiering.
Fixture aliases file at `core/tests/fixtures/news/masi_aliases_test.json`
(small subset, not the live `data/masi_aliases.json`, so alias-table edits
don't silently change test behavior).
