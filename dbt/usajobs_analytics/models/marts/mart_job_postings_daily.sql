with base as (
    select
        date_trunc('day', ingested_at)::date as snapshot_date,
        search_name,
        keyword,
        location,
        organization_name,
        matched_object_id
    from {{ ref('stg_usajobs_postings') }}
),

deduped as (
    -- prevent double when the same posting appears on multiple pages/runs that day
    select distinct
        snapshot_date,
        search_name,
        keyword,
        location,
        organization_name,
        matched_object_id
    from base    
)

select
    snapshot_date,
    search_name,
    keyword,
    location,
    organization_name,
    count(*) as postings_count
from deduped
group by 1,2,3,4,5
order by snapshot_date desc, postings_count desc