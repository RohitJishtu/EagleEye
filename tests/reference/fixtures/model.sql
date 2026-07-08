{{ config(materialized='table') }}

with health as (
    select * from {{ ref('fct_account_health') }}
),
opp as (
    select * from {{ source('salesforce', 'opportunity') }}
)
select h.account_id, o.amount
from health h
join opp o on o.account_id = h.account_id
