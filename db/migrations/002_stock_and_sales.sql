-- Stock snapshots and sales records
-- Run order: 2 of 3 (requires 001)

create table if not exists stock_log (
    log_id     serial primary key,
    sku_id     int not null references skus (sku_id),
    quantity   numeric(10, 2) not null,
    logged_at  timestamptz not null default now(),
    source     text not null default 'telegram'  -- 'telegram' | 'manual'
);

create table if not exists sales (
    sale_id    serial primary key,
    sku_id     int not null references skus (sku_id),
    quantity   numeric(10, 2) not null,
    sale_date  date not null,
    logged_at  timestamptz not null default now(),
    source     text not null default 'telegram'
);

create index if not exists idx_sales_sku_date on sales (sku_id, sale_date);
