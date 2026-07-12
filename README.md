# WarungOS

A data platform for one real warung, run entirely from a smartphone over Telegram. It helps a mixed grocery and fresh goods stall decide what to restock, how much fresh stock to hold without waste, and which regular customers to extend store credit to and how much.

## Architecture

```
Telegram  ->  FastAPI webhook (Hugging Face Space)  ->  Supabase Postgres
                                                              |
                                  GitHub Actions cron (nightly + morning + evening)
                                                              |
                          forecasting + inventory policy + credit scorecard
                                                              |
                       Telegram digests (Bahasa)        GitHub Pages portfolio
```

## Milestones

| Milestone | Deliverable | Ships value to the merchant? |
|---|---|---|
| M0 | Repo scaffold, Supabase schema, secrets, CI lint | No |
| M1 | Synthetic warung generator + offline model validation | No |
| M2 | Telegram webhook: log a sale, log stock, get a morning digest | Yes |
| M3 | Forecasting + inventory policy live in the digest | Yes |
| M4 | Kasbon ledger, reminders, explainable scorecard | Yes |
| M5 | Repayment survival model, portfolio site | Polish |

## Running locally

```bash
git clone <repo-url>
cd warung-os
cp .env.example .env   # fill in your secrets
pip install -r requirements.txt
uvicorn bot.main:app --reload
```

Health check: `curl http://localhost:8000/health`

## Supabase schema

Apply migrations in order:

```bash
psql $SUPABASE_URL -f db/migrations/001_init_catalog.sql
psql $SUPABASE_URL -f db/migrations/002_stock_and_sales.sql
psql $SUPABASE_URL -f db/migrations/003_kasbon.sql
```

## Stack

Python 3.11, FastAPI, httpx, supabase-py, pandas, numpy, scipy, statsmodels, lifelines, matplotlib, pytest. Hosted on a Hugging Face Space (FastAPI in Docker). Storage on Supabase Postgres. Cron via GitHub Actions.
