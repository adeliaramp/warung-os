-- Per-debt repayment probability from the Cox model
-- Written by the nightly_recompute job.
-- One row per open debt per cache_date.

create table if not exists repayment_predictions (
    pred_id       serial primary key,
    ledger_id     int not null references kasbon_ledger (ledger_id),
    cache_date    date not null,
    computed_at   timestamptz not null default now(),
    p30           numeric(6, 4) not null,  -- P(repaid within 30 days)
    model_type    text not null default 'cox'  -- 'cox' | 'km_fallback'
);

create unique index if not exists idx_repayment_pred_debt_date
    on repayment_predictions (ledger_id, cache_date);

create index if not exists idx_repayment_pred_date
    on repayment_predictions (cache_date);
