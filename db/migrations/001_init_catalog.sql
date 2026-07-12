-- SKU catalog
-- Run order: 1 of 3

create table if not exists skus (
    sku_id        serial primary key,
    name          text not null,
    unit          text not null,               -- e.g. "pcs", "bungkus", "kg"
    category      text not null,              -- e.g. "dry", "fresh", "beverage"
    is_perishable boolean not null default false,
    cost_price    numeric(10, 2),             -- purchase price per unit (IDR)
    sell_price    numeric(10, 2),             -- selling price per unit (IDR)
    is_active     boolean not null default true,
    created_at    timestamptz not null default now()
);
