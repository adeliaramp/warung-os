-- Nightly credit scorecard cache
-- Written by the nightly_recompute job, read by morning_digest and /kasbon command.
-- One row per customer per cache_date.

create table if not exists credit_cache (
    cache_id          serial primary key,
    customer_id       int not null references customers (customer_id),
    cache_date        date not null,
    computed_at       timestamptz not null default now(),
    score             int,                   -- null for thin-file customers
    band              text not null,         -- hijau / kuning / merah / thin_file
    outstanding       numeric(10, 2) not null default 0,
    suggested_limit   numeric(10, 2),
    days_since_borrow int                    -- days since most recent open debt
);

create unique index if not exists idx_credit_cache_customer_date
    on credit_cache (customer_id, cache_date);

create index if not exists idx_credit_cache_date
    on credit_cache (cache_date);
