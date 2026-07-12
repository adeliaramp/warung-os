-- Kasbon (store credit) ledger
-- Run order: 3 of 3 (requires 001)
-- PII minimized: initials + shop-assigned local code only.
-- consent_at must be populated before any credit entry is made for a customer.

create table if not exists customers (
    customer_id  serial primary key,
    local_code   text not null unique,  -- e.g. "BU-001", assigned by the shop
    initials     text not null,         -- e.g. "SR"
    tenure_start date not null,
    consent_at   timestamptz,           -- null = consent not yet recorded
    is_active    boolean not null default true,
    created_at   timestamptz not null default now()
);

create table if not exists kasbon_ledger (
    ledger_id   serial primary key,
    customer_id int not null references customers (customer_id),
    amount      numeric(10, 2) not null check (amount > 0),
    note        text,
    borrowed_at timestamptz not null default now(),
    is_cleared  boolean not null default false
);

create table if not exists kasbon_repayments (
    repayment_id serial primary key,
    ledger_id    int not null references kasbon_ledger (ledger_id),
    amount       numeric(10, 2) not null check (amount > 0),
    repaid_at    timestamptz not null default now()
);

create index if not exists idx_kasbon_customer on kasbon_ledger (customer_id, borrowed_at);
create index if not exists idx_repayments_ledger on kasbon_repayments (ledger_id);
