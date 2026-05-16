from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

USAJOBS_SEARCH_URL = "https://data.usajobs.gov/api/search"

@dataclass(frozen=True)
class SearchConfig:
    name: str
    keyword: Optional[str]
    location: Optional[str]


def load_searches(yaml_path: Path) -> List[SearchConfig]:
    data: Dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    if not isinstance(data, dict) or "searches" not in data:
        raise ValueError("searches.yml must have a top-level key: searches")
    
    searches = data["searches"]
    if not isinstance(searches, list):
        raise ValueError("'searches' must be a list")
    
    out: List[SearchConfig] = []
    for i, item in enumerate(searches):
        if not isinstance(item, dict):
            raise ValueError(f"searches[{i}] must be a mapping/object")
        
        name = item.get("name")
        keyword = item.get("keyword")
        location = item.get("location")

        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"searches[{i}].name must be a non-empty string.")
        if keyword is not None and not isinstance(keyword, str):
            raise ValueError(f"searches[{i}].keyword must be a string or null")
        if location is not None and not isinstance(location, str):
            raise ValueError(f"searches[{i}].location must be a string or null")
        
        out.append(
            SearchConfig(
                name=name.strip(),
                keyword=keyword.strip() if isinstance(keyword, str) else None,
                location=location.strip() if isinstance(location, str) else None
            )
        )

    return out

def build_usajobs_headers() -> Dict[str, str]:
    email = os.getenv("USAJOBS_EMAIL")
    api_key = os.getenv("USAJOBS_API_KEY")
    if not email or not api_key:
        raise RuntimeError("Missing USAJOBS_EMAIL or USAJOBS_API_KEY in .env")
    
    return {
        "Host": "data.usajobs.gov",
        "User-Agent": email,
        "Authorization-Key": api_key,
        "Accept": "application/json"
    }
def fetch_page(
        session: requests.Session,
        headers: Dict[str, str],
        keyword: Optional[str],
        location: Optional[str],
        page: int,
        results_per_page: int = 250
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"Page": page, "ResultsPerPage": results_per_page}
    if keyword:
        params["Keyword"] = keyword
    if location:
        params["LocationName"] = location

    resp = session.get(USAJOBS_SEARCH_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

def extract_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = payload.get("SearchResult", {}).get("SearchResultItems", [])
    return items if isinstance(items, list) else []

def pg_connect_local() -> psycopg2.extensions.connection:
    user = os.getenv("POSTGRES_USER", "warehouse")
    password = os.getenv("POSTGRES_PASSWORD", "warehouse")
    db = os.getenv("POSTGRES_DB", "jobs")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    return psycopg2.connect(host=host, port=port, dbname=db, user=user, password=password)

def insert_raw_page(
        conn: psycopg2.extensions.connection,
        run_id: str,
        ingested_at: datetime,
        search: SearchConfig,
        page_number: int,
        payload: Dict[str, Any]
) -> None:
    sql = """
    INSERT INTO raw.usajobs_search_results
      (run_id, ingested_at, search_name, keyword, location, page_number, response_json)
    VALUES 
      (%s, %s, %s, %s, %s, %s, %s::jsonb);
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                run_id,
                ingested_at,
                search.name,
                search.keyword,
                search.location,
                page_number,
                json.dumps(payload),
            ),
        )

def run_ingestion(searches_yaml: Path, max_pages_per_search: int = 5) -> str:
    run_id = str(uuid.uuid4())
    ingested_at = datetime.now(timezone.utc)

    searches = load_searches(searches_yaml)
    headers = build_usajobs_headers()

    print(f"[INFO] run_id={run_id} ingested_at={ingested_at.isoformat()} searches={len(searches)}")

    session = requests.Session()
    conn = pg_connect_local()
    conn.autocommit = False

    try:
        for search in searches:
            print(f"[INFO] search={search.name} keyword={search.keyword!r} location={search.location!r}")
            page = 1
            while page <= max_pages_per_search:
                payload = fetch_page(session, headers, search.keyword, search.location, page)
                items = extract_items(payload)

                insert_raw_page(conn, run_id, ingested_at, search, page, payload)
                conn.commit()

                print(f"[INFO] inserted page={page} items={len(items)}")
                if len(items) == 0:
                    break
                page += 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        session.close()
    
    print(f"[DONE] run_id={run_id}")
    return run_id

if __name__ == "__main__":
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "searches.yml"
    run_ingestion(cfg_path)