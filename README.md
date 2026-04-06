# USAJOBS Analytics (dbt + Airflow)

This project ingests postings from the USAJOBS API, loads raw data into Postgres, transforms it with dbt, orchestrates runs with Airflow, and powers a Power BI dashboard.

## High-level flow
YAML searches -> Ingestion (Python) -> raw tables (Postgres) -> dbt models -> marts -> Power BI