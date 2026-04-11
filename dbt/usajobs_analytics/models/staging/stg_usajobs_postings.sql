with pages as (
  select
    run_id,
    ingested_at,
    search_name,
    keyword,
    location,
    response_json
  from {{ source('raw', 'usajobs_search_results') }}
),

items as (
  select
    p.run_id,
    p.ingested_at,
    p.search_name,
    p.keyword,
    p.location,
    x.item
  from pages p
  cross join lateral jsonb_array_elements(
    coalesce(p.response_json->'SearchResult'->'SearchResultItems', '[]'::jsonb)
  ) as x(item)
),

postings as (
  select
    run_id,
    ingested_at,
    search_name,
    keyword,
    location,

    item->>'MatchedObjectId' as matched_object_id,
    item->'MatchedObjectDescriptor'->>'PositionID' as position_id,
    item->'MatchedObjectDescriptor'->>'PositionTitle' as position_title,
    item->'MatchedObjectDescriptor'->>'OrganizationName' as organization_name,
    item->'MatchedObjectDescriptor'->>'PositionLocationDisplay' as position_location_display,

    -- safer casts: only cast if the string looks like a date
    case
      when (item->'MatchedObjectDescriptor'->>'PositionStartDate') ~ '^\d{4}-\d{2}-\d{2}'
        then (item->'MatchedObjectDescriptor'->>'PositionStartDate')::timestamptz
      else null
    end as position_start_date,

    case
      when (item->'MatchedObjectDescriptor'->>'PositionEndDate') ~ '^\d{4}-\d{2}-\d{2}'
        then (item->'MatchedObjectDescriptor'->>'PositionEndDate')::timestamptz
      else null
    end as position_end_date,

    -- ApplyURI is often an array -> take first element
    item->'MatchedObjectDescriptor'->'ApplyURI'->>0 as apply_uri

  from items
)

select *
from postings
where matched_object_id is not null