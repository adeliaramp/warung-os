-- Add a display_name column so the owner can refer to customers by
-- their natural name (e.g. "Bu Sri") instead of the initials code.
-- Nullable: existing customers can be migrated gradually.

alter table customers add column if not exists display_name text;

-- Index for fast lookup by display_name
create index if not exists idx_customers_display_name on customers (display_name);
