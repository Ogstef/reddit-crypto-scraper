# sentiment-scraper

Standalone scraper microservice that browses Reddit and CryptoPanic and POSTs batches of posts to the [revolut-trading-bot](../../revolut-trading-bot) Java backend for classification and trading.

## Why this exists

- Reddit API requires handing over username/password (script-app auth) — not acceptable.
- CryptoPanic's free tier was retired in favour of a ~€50/week paid plan — ~20× over budget.

This scraper uses only public web endpoints. The Java backend is the decision-maker — it classifies, aggregates, and trades.

## Quick start (local)

```bash
cd scrapers/sentiment-scraper
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# edit .env — set SCRAPER_INGEST_TOKEN to match the Java side's sentiment.ingest.auth-token

sentiment-scraper       # runs the APScheduler loop in the foreground
```

## Docker

```bash
docker build -t sentiment-scraper .
docker run --rm \
    --env-file .env \
    -v sentiment-scraper-dedup:/var/lib/sentiment-scraper \
    sentiment-scraper
```

On the VPS, point this at the backend service via `SCRAPER_INGEST_BASE_URL=http://revolut-trading-bot:8089` (or the public URL).

## Layout

```
src/sentiment_scraper/
├── main.py               # APScheduler entrypoint
├── config.py             # Settings (pydantic-settings, reads env / .env)
├── models.py             # Pydantic DTOs — mirror the Java @Valid request bodies
├── ingest_client.py      # httpx POST with Bearer auth + retry/backoff
├── dedup.py              # SQLite (source, external_id) → first_seen
├── reddit/
│   ├── scraper.py        # old.reddit.com/.json
│   └── pair_matcher.py   # title+body keyword → pair
└── cryptopanic/
    ├── scraper.py        # cryptopanic.com HTML parser
    └── dom.py            # selectors + parsers (swap-in if site changes)
```

## Env vars

See [`.env.example`](.env.example) for the full list. The two required ones are:

| Var | Purpose |
|---|---|
| `SCRAPER_INGEST_TOKEN` | Shared bearer token — must match Java `sentiment.ingest.auth-token` |
| `SCRAPER_INGEST_BASE_URL` | Java backend base URL (e.g. `http://localhost:8089`) |

## Tests

```bash
pytest
```

Fixtures in [`tests/fixtures/`](tests/fixtures/) are saved HTML/JSON snapshots — updating them is the canonical way to catch regressions when Reddit or CryptoPanic change their layout.

## Troubleshooting

- **403/429 from Reddit**: rotate `SCRAPER_REDDIT_USER_AGENT` to a more human-looking string, increase the interval, or drop subreddits. Playwright fallback is a future option.
- **Empty CryptoPanic responses**: the site is JS-heavy — if BS4 is getting nothing, swap in Playwright (not currently installed — adds ~500 MB to the image).
- **401 from Java**: check `SCRAPER_INGEST_TOKEN` matches both sides (exact string, no trailing whitespace).
