select * from {{ ref('sales_orders') }} where amount < 0
