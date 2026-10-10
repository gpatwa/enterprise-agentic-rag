select id, amount, status, created_at from {{ source('warehouse', 'orders') }}
