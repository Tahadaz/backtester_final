# LLM Scoring Pipeline (A3)

## Provider-agnostic client — no new SDK deps

Every candidate provider (OpenRouter, Groq, Google's Gemini OpenAI-compat
endpoint, a self-hosted Ollama instance) exposes an **OpenAI-compatible
chat-completions endpoint**: `POST {base_url}/chat/completions` with body
`{"model", "messages": [...], "temperature", "max_tokens",
"response_format": {"type": "json_object"}}` and header
`Authorization: Bearer {api_key}`. This layer talks to that endpoint with a
raw `urllib.request` POST (same standard-library approach as
`stockanalysis_provider.py` — no `requests`, no `openai` SDK, no per-provider
client library). One function, `llm_client.py::chat_completion(provider:
ProviderSpec, messages: list[dict], **kwargs) -> str`, works against every
provider because they all speak the same wire format.

`core/quant_core/research/sentiment/llm_client.py`:

```python
def chat_completion(provider: ProviderSpec, messages: list[dict], *,
                     max_tokens: int, temperature: float = 0.1,
                     timeout_seconds: int = 30) -> str:
    """POST to provider.base_url + '/chat/completions'; returns the
    assistant message content string. Raises ProviderQuotaError on 429,
    ProviderUnavailableError on 5xx/timeout/connection error."""
```

Ollama's OpenAI-compat surface (`http://{host}:11434/v1/chat/completions`)
implements the same contract, which is why the fallback tier requires no
special-casing in `chat_completion` — only a different `base_url` and no
`api_key_env`.

## Provider registry

Configured entirely via one environment variable, `SENTIMENT_LLM_PROVIDERS`,
a JSON array — no provider-specific code paths, adding/removing/reordering
providers is a config change:

```json
[
  {
    "name": "openrouter_kimi",
    "base_url": "https://openrouter.ai/api/v1",
    "model": "moonshotai/kimi-k2:free",
    "api_key_env": "OPENROUTER_API_KEY",
    "rpm": 20,
    "rpd": 200,
    "max_tokens": 800
  },
  {
    "name": "openrouter_glm",
    "base_url": "https://openrouter.ai/api/v1",
    "model": "z-ai/glm-4.5-air:free",
    "api_key_env": "OPENROUTER_API_KEY",
    "rpm": 20,
    "rpd": 200,
    "max_tokens": 800
  },
  {
    "name": "groq",
    "base_url": "https://api.groq.com/openai/v1",
    "model": "llama-3.3-70b-versatile",
    "api_key_env": "GROQ_API_KEY",
    "rpm": 30,
    "rpd": 1000,
    "max_tokens": 800
  },
  {
    "name": "gemini_compat",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "model": "gemini-2.0-flash",
    "api_key_env": "GEMINI_API_KEY",
    "rpm": 15,
    "rpd": 1500,
    "max_tokens": 800
  },
  {
    "name": "ollama_qwen3",
    "base_url": "http://<oci-vm-host>:11434/v1",
    "model": "qwen3:8b",
    "api_key_env": null,
    "rpm": 6,
    "rpd": 100000,
    "max_tokens": 800
  }
]
```

### Entry schema

| Field | Type | Meaning |
|---|---|---|
| `name` | str | unique provider id, used as the Redis quota-counter key and in `alt_news_score.provider` |
| `base_url` | str | OpenAI-compat base URL, no trailing slash, no `/chat/completions` suffix |
| `model` | str | model id passed in the request body |
| `api_key_env` | str \| null | name of the env var holding the API key; `null` for unauthenticated local endpoints (Ollama) |
| `rpm` | int | requests/minute soft cap (client-side throttle, not enforced server-side by us) |
| `rpd` | int | requests/day hard cap — this is what the Redis quota counter enforces |
| `max_tokens` | int | passed through to the completion request |

If `SENTIMENT_LLM_PROVIDERS` is unset, `llm_client.py` falls back to the
five-entry list above as a hardcoded default (matching the user's locked
provider order: OpenRouter free-tier Kimi/GLM → Groq → Gemini OpenAI-compat
→ Ollama `qwen3:8b` on the OCI Always-Free ARM VM).

## Redis quota counters and rotation

- Key: `sent_llm:{provider_name}:{yyyymmdd}` (UTC date), a Redis `INCR`
  counter with `EXPIRE` set to 2 days on first increment (survives a
  midnight rollover query without leaking keys forever).
- Before each scoring call, `scoring.py::pick_provider(providers:
  list[ProviderSpec]) -> ProviderSpec | None` iterates the registry in
  **list order** (i.e. the order is the priority — OpenRouter first) and
  returns the first provider whose `GET sent_llm:{name}:{today}` is `<
  rpd`. `rpm` is enforced client-side with a simple token-bucket sleep
  inside `chat_completion`'s caller loop, not via Redis (rpm windows are too
  short to bother with cross-process coordination at this scale).
- On a successful call, `INCR sent_llm:{provider}:{today}`. On a `429` /
  quota-exceeded response mid-call, the counter is set to `rpd` immediately
  (rather than waiting for natural exhaustion) so the next `pick_provider`
  call skips it for the rest of the day even if our local count was
  under-tracking actual usage.
- If **all** providers are at quota, `pick_provider` returns `None` and the
  calling RQ task (`score_news_sentiment.py`) re-enqueues itself with a
  **30-minute delay** (`queue.enqueue_in(timedelta(minutes=30), ...)`)
  rather than failing or busy-polling. This is the same "park and retry"
  posture used elsewhere in the alt-data program for exhausted external
  resources.

## Prompt v1

Two-part system prompt (French + English, since Moroccan financial news is
overwhelmingly French-language and global/GDELT sources are English) with a
strict JSON-only instruction. The model is instructed to identify every
distinct subject discussed and score each independently — this produces the
1..N fan-out into `alt_news_score` rows described in
[00-overview.md](00-overview.md#subject-keys).

**System prompt (abridged, full text lives in `prompts.py::SYSTEM_PROMPT_V1`)**:

> You are a financial news sentiment analyst covering Moroccan (MASI) and
> global markets. Tu es un analyste de sentiment financier couvrant les
> marchés marocains (MASI) et mondiaux. Given one news article, identify
> every distinct subject it discusses — companies, and/or topic×region
> pairs from this fixed taxonomy: topics = {company_specific, macro,
> economics, geopolitics, politics, markets, commodities, other}; regions =
> {ma, us, eu, asia, global}. For each subject, output a sentiment score in
> [-1, 1] (negative = bearish/adverse, positive = bullish/favorable),
> a confidence in [0, 1] (how certain you are this subject is actually
> discussed, not how confident you are in the sentiment direction), a
> direction label ("bullish"|"bearish"|"neutral"), and a relevance in
> [0, 1] (how central this subject is to the article, vs. mentioned in
> passing). Respond with **strict JSON only**, no prose, no markdown code
> fences, matching exactly this schema. If the article names a company but
> you do not recognize it as Moroccan-listed, still emit a
> `company_specific`/`ma`-or-`global` topic_region subject rather than
> guessing a ticker — entity-to-symbol mapping happens downstream.

**Example output** (`schema.py::SentimentScoreResponse`, one article about
an Attijariwafa Bank earnings beat that also touches BAM policy):

```json
{
  "subjects": [
    {
      "type": "symbol",
      "key": "ATW",
      "sentiment": 0.62,
      "confidence": 0.91,
      "direction": "bullish",
      "relevance": 0.95
    },
    {
      "type": "topic_region",
      "key": "macro:ma",
      "sentiment": 0.15,
      "confidence": 0.6,
      "direction": "neutral",
      "relevance": 0.3
    }
  ]
}
```

The client wraps this in the persisted-row shape by adding
`subject_type`/`subject_key` split from `type`/`key` (`symbol:ATW` or
`topic_region:macro:ma`, matching the taxonomy's key format), plus the
provenance columns below, before insert.

### Validation and clipping

`schema.py::validate_response(raw_json: str) -> list[SubjectScore]`:

- Parse as JSON; reject (→ malformed-JSON path below) on parse failure or a
  missing `subjects` key.
- Each subject: `type` must be `"symbol"` or `"topic_region"`; `key` for
  `topic_region` must decompose into a known topic and region from the
  frozen taxonomy (unknown topic/region → subject dropped, not the whole
  response rejected — one bad subject shouldn't discard four good ones).
- `sentiment` clipped to `[-1, 1]`, `confidence` and `relevance` clipped to
  `[0, 1]` (models occasionally emit `1.05` or similar — clip, don't
  reject).
- `direction` cross-checked against `sentiment` sign only for logging/QA
  (mismatch is not fatal — e.g. `sentiment=0.05, direction="neutral"` is
  fine); not enforced as a hard validation failure since it's a redundant
  field included for model self-consistency, not ground truth.
- Empty `subjects` list is valid (article judged to contain no in-taxonomy
  subject) and persists zero `alt_news_score` rows for that article, but
  the article is still marked `scored_at` so it isn't re-queued forever.

### Malformed JSON: repair-retry-then-park

1. First response fails to parse or fails schema validation entirely (not
   just a clipped field) → **one repair retry**: re-send the same messages
   plus a corrective system message ("Your previous response was not valid
   JSON matching the schema. Return ONLY the corrected JSON, no
   explanation.") to the **same provider** (repair retries don't rotate
   providers — a malformed response is a prompt-following failure, not a
   quota/availability failure).
2. If the repair retry also fails validation, the article is **parked**:
   no `alt_news_score` rows are written, but a row is written to
   `alt_news_item` metadata (or a lightweight parking table —
   `alt_news_score_error(news_item_id, provider, prompt_version, error,
   parked_at)`) so it doesn't get silently re-attempted every scoring cycle.
   A parked article can be manually or periodically re-tried against a
   different provider (operational tooling, not built in A3).

## Batching

- **Batch size N=50** articles per LLM invocation cycle is a scheduling
  granularity, not one-call-per-50-articles — each article is still one
  chat-completion call (GDELT/scraped text varies too much in length to
  safely pack multiple articles into one prompt without confusing subject
  attribution). N=50 is how many articles `score_news_sentiment.py` pulls
  off the unscored queue per RQ job invocation, so a quota exhaustion or
  provider rotation event is detected within a bounded batch rather than
  mid-way through an unbounded pull.
- **Priority order** within the unscored queue: `symbol-mapped` articles
  (already tagged with a candidate `symbol:*` subject by A4's entity
  mapping) first, then `topic_region:macro:ma`-candidate articles (Morocco
  macro is the most product-relevant slice), then everything else
  (`global`/other topic_region candidates) last. Implemented as an `ORDER
  BY` on a priority-rank column derived at query time from
  `alt_news_item.symbols` (non-empty JSONB array → rank 0) and
  `alt_news_item.regions`/`topics` (contains `ma` + `macro` → rank 1; else
  rank 2), not a persisted column — priority is a query-time projection of
  already-stored ingest metadata (`symbols`/`topics`/`regions` JSONB set by
  A4 entity mapping and topic/region hints).

## Anonymization option

Optional per-run flag (`SENTIMENT_ANONYMIZE_ENTITIES=true`) that, before
sending the article to the LLM, replaces recognized company names with
placeholder tokens (`SOCIETE_A`, `SOCIETE_B`, ... — assigned per-article,
not globally stable) using the same alias table as A4's entity mapping. This
exists to let a later research pass measure how much of the LLM's sentiment
score is driven by brand recognition/reputation priors vs. the actual
content of the article — a check against a specific class of lookahead
contamination (the model "knowing" a company is currently doing well from
training data, independent of what this particular article says).
`anonymized: bool` is recorded per score row regardless of whether the flag
was on, so anonymized and non-anonymized scores of the same article
(produced by re-running scoring with the flag toggled) are distinguishable
and comparable.

## Lookahead-bias provenance

Every `alt_news_score` row carries, in addition to the score fields:

| Column | Purpose |
|---|---|
| `model_id` | exact model string sent in the request (e.g. `moonshotai/kimi-k2:free`) |
| `provider` | provider registry `name` that served the call |
| `prompt_version` | e.g. `"v1"` — bumped on any system-prompt or taxonomy change |
| `anonymized` | whether entity-anonymization was applied to this call |
| `scored_at` | wall-clock timestamp of scoring, **distinct from** `alt_news_item.published_at` |

This is what lets the validation study in
[05-validation-gates.md](05-validation-gates.md) and the shared policy in
[../alt-data-foundation/02-validation-policy.md](../alt-data-foundation/02-validation-policy.md)
determine, per score, whether `scored_at` happened close to `published_at`
(a genuinely live, PIT-clean score) or long after (a score of old news by a
model whose training data may post-date the event — `pit_grade
='upper_bound'`, reported separately, never promotion-eligible). Full
column definitions live in
[../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md).

## GDELT V2Tone as zero-cost fallback

`alt_news_item.payload_json.v2tone` (captured at ingest per
[01-data-sources.md](01-data-sources.md)) is a usable sentiment proxy with
zero LLM cost and zero quota risk. It is not a substitute for LLM scoring —
it's a single scalar with no per-subject breakdown and no topic/region
attribution — but `aggregate.py` ([04-aggregation-and-factors.md](04-aggregation-and-factors.md))
can compute a coarse `topic_region:markets:global`-style daily aggregate
from V2Tone alone for GDELT-sourced items even before A3 has scored them,
and continues doing so as a degraded-mode fallback during any full-quota
outage window across all five providers.

## Files

- `core/quant_core/research/sentiment/llm_client.py` — `ProviderSpec`,
  `chat_completion()`, quota check/increment helpers.
- `core/quant_core/research/sentiment/prompts.py` — `SYSTEM_PROMPT_V1`,
  `build_user_message(article_text: str) -> str`.
- `core/quant_core/research/sentiment/schema.py` — `SubjectScore`,
  `SentimentScoreResponse`, `validate_response()`.
- `core/quant_core/research/sentiment/scoring.py` — `pick_provider()`,
  `score_article(item, providers) -> list[SubjectScore] | None` (orchestrates
  client + prompt + schema + repair retry).
- `services/worker/tasks/score_news_sentiment.py` — RQ task pulling batches
  of N=50 off the priority-ordered unscored queue, calling `scoring.py`,
  persisting `alt_news_score` rows, and re-enqueueing with a 30-minute delay
  on full quota exhaustion.

## Tests

`core/tests/test_sentiment_scoring.py` — schema validation (valid, clipped,
malformed-then-repaired, malformed-then-parked cases) and provider rotation
/ quota-exhaustion logic, all against a fake `chat_completion` (no live LLM
calls in tests). `core/tests/fixtures/news/llm_responses/` holds canned
valid/malformed/repaired JSON strings used by those tests.
