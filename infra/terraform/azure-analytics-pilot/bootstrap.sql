-- Run once after `terraform apply`, as the PostgreSQL administrator, against the analytics_warehouse database:
--   psql "host=<postgres_host> dbname=analytics_warehouse user=analyticsadmin sslmode=require" \
--        -v readonly_password="$POSTGRES_READONLY_PASSWORD" -f bootstrap.sql
-- Creates the read-only role the API uses for the warehouse, and the pilot's sample table. Replace the sample data with the
-- tenant's real (certified) dataset before real users; the governed compiler only ever reads tables named in the certified contract.

SELECT format('CREATE ROLE analytics_readonly LOGIN PASSWORD %L', :'readonly_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_readonly') \gexec

CREATE TABLE IF NOT EXISTS sales_orders (
  id text PRIMARY KEY,
  amount numeric(12, 2) NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL
);

-- Sample data matching the reference corpus (100 orders, January to March 2024). Remove for real data.
INSERT INTO sales_orders
SELECT 'o' || i, i, CASE WHEN i % 5 = 0 THEN 'refunded' ELSE 'paid' END,
       TIMESTAMPTZ '2024-01-01 00:00:00+00' + make_interval(hours => i * 20)
FROM generate_series(1, 100) AS i
ON CONFLICT (id) DO NOTHING;

GRANT CONNECT ON DATABASE analytics_warehouse TO analytics_readonly;
GRANT USAGE ON SCHEMA public TO analytics_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analytics_readonly;
ALTER ROLE analytics_readonly SET default_transaction_read_only = on;
