from __future__ import annotations
from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="usajobs_ingestion",
    start_date=datetime(2026,4,11),
    schedule="@daily",
    catchup=False,
    tags=["usajobs"],
) as dag:
    ingest = BashOperator(
        task_id="ingest_usajobs",
        bash_command="python /opt/airflow/ingestion/usajobs_ingest.py",
    )

    ingest