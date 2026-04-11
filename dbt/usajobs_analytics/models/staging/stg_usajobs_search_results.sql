with source as (
    select
        id,
        run_id,
        ingested_at,
        search_name,
        keyword,
        location,
        page_number,
        response_json
    from {{ source('raw', 'usajobs_search_results') }}
)

select * from source