-- Nightly restock recommendation cache
-- Run order: 4 of 4 (requires 001)
-- Written by the nightly_recompute job, read by morning_digest.
-- One row per SKU per cache_date. The UNIQUE index ensures the
-- nightly job can upsert safely without accumulating stale rows.

create table if not exists restock_cache (
    cache_id     serial primary key,
    sku_id       int not null references skus (sku_id),
    cache_date   date not null,
    computed_at  timestamptz not null default now(),
    demand_class text not null,
    daily_rate   numeric(10, 3) not null,
    rop          numeric(10, 2),   -- null for perishables (newsvendor policy)
    order_qty    numeric(10, 2),   -- recommended order quantity
    is_perishable boolean not null default false
);

create unique index if not exists idx_restock_cache_sku_date
    on restock_cache (sku_id, cache_date);

create index if not exists idx_restock_cache_date
    on restock_cache (cache_date);
