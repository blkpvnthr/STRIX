-- Company dimension, standardized. company_name from SEC entityName when
-- available, else NULL (never invented).
with src as (
    select * from {{ source('warehouse', 'dim_company') }}
)
select
    cik,
    company_sk,
    company_name
from src
