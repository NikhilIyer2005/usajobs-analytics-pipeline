import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock

import pytest
import requests

import ingestion.usajobs_ingest as ingestion_module
from ingestion.usajobs_ingest import (
    USAJOBS_SEARCH_URL,
    build_usajobs_headers,
    extract_items,
    fetch_page,
    load_searches,
)


def test_load_searches_valid_yaml(tmp_path):
    config = tmp_path / "searches.yml"
    config.write_text(
        "searches:\n"
        "  - name: data_engineer_orlando\n"
        "    keyword: data engineer\n"
        "    location: Orlando, FL\n",
        encoding="utf-8",
    )

    searches = load_searches(config)

    assert len(searches) == 1
    assert searches[0].name == "data_engineer_orlando"
    assert searches[0].keyword == "data engineer"
    assert searches[0].location == "Orlando, FL"


def test_load_searches_rejects_invalid_yaml_structure(tmp_path):
    config = tmp_path / "searches.yml"
    config.write_text("searches: invalid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a list"):
        load_searches(config)


def test_extract_items_from_api_response():
    items = [{"MatchingObjectId": "12345"}]
    payload = {
        "SearchResult": {
            "SearchResultItems": items,
        }
    }

    assert extract_items(payload) == items


def test_extract_items_handles_invalid_items():
    payload = {
        "SearchResult": {
            "SearchResultItems": "invalid",
        }
    }

    assert extract_items(payload) == []


def test_build_usajobs_headers(monkeypatch):
    monkeypatch.setenv("USAJOBS_EMAIL", "test@example.com")
    monkeypatch.setenv("USAJOBS_API_KEY", "fake-test-key")

    headers = build_usajobs_headers()

    assert headers["User-Agent"] == "test@example.com"
    assert headers["Authorization-Key"] == "fake-test-key"
    assert headers["Accept"] == "application/json"


def test_fetch_page_uses_correct_parameters():
    response = Mock()
    response.json.return_value = {"SearchResult": {"SearchResultItems": []}}

    session = Mock()
    session.get.return_value = response

    headers = {"Authorization-Key": "fake-test-key"}

    result = fetch_page(
        session=session,
        headers=headers,
        keyword="data engineer",
        location="Orlando, FL",
        page=1,
    )

    session.get.assert_called_once_with(
        USAJOBS_SEARCH_URL,
        headers=headers,
        params={
            "Page": 1,
            "ResultsPerPage": 250,
            "Keyword": "data engineer",
            "LocationName": "Orlando, FL",
        },
        timeout=30,
    )

    response.raise_for_status.assert_called_once_with()
    assert result == {"SearchResult": {"SearchResultItems": []}}


def test_load_searches_missing_searches_key(tmp_path):
    config = tmp_path / "searches.yml"
    config.write_text("other: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="top-level key"):
        load_searches(config)


def test_load_searches_rejects_empty_name(tmp_path):
    config = tmp_path / "searches.yml"
    config.write_text(
        "searches:\n   - name: ''\n     keyword: data engineer\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-empty string"):
        load_searches(config)


def test_build_usajobs_headers_missing_credentials(monkeypatch):
    monkeypatch.delenv("USAJOBS_EMAIL", raising=False)
    monkeypatch.delenv("USAJOBS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Missing USAJOBS_EMAIL"):
        build_usajobs_headers()


def test_fetch_page_handles_api_error():
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError("429 Too Many Requests")

    session = Mock()
    session.get.return_value = response

    with pytest.raises(requests.HTTPError, match="429"):
        fetch_page(
            session=session,
            headers={"Authorization-Key": "fake-test-key"},
            keyword="data engineer",
            location="Orlando, FL",
            page=1,
        )

    session.get.assert_called_once()
    response.raise_for_status.assert_called_once()
    response.json.assert_not_called()


def test_insert_raw_page():
    conn = MagicMock()

    search = ingestion_module.SearchConfig(
        name="data_engineer_orlando",
        keyword="data engineer",
        location="Orlando, FL",
    )

    payload = {"SearchResult": {"SearchResultItems": [{"MatchedObjectId": "12345"}]}}

    ingested_at = datetime(2026, 11, 16, tzinfo=timezone.utc)

    ingestion_module.insert_raw_page(
        conn=conn,
        run_id="test-run-123",
        ingested_at=ingested_at,
        search=search,
        page_number=1,
        payload=payload,
    )

    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.execute.assert_called_once()

    sql, params = cursor.execute.call_args.args

    assert "INSERT INTO raw.usajobs_search_results" in sql
    assert params[0] == "test-run-123"
    assert params[1] == ingested_at
    assert params[2] == "data_engineer_orlando"
    assert params[5] == 1
    assert json.loads(params[6]) == payload


def test_run_ingestion_stops_after_empty_page(monkeypatch, tmp_path):
    search = ingestion_module.SearchConfig(
        name="data_engineer_orlando",
        keyword="data engineer",
        location="Orlando, FL",
    )

    conn = MagicMock()
    session = MagicMock()

    monkeypatch.setattr(ingestion_module, "load_searches", lambda _: [search])
    monkeypatch.setattr(
        ingestion_module,
        "build_usajobs_headers",
        lambda: {"Authorization-Key": "fake-test-key"},
    )
    monkeypatch.setattr(ingestion_module, "pg_connect_local", lambda: conn)
    monkeypatch.setattr(ingestion_module.requests, "Session", lambda: session)

    fake_fetch = Mock(
        side_effect=[
            {"SearchResult": {"SearchResultItems": [{"MatchedObjectId": "12345"}]}},
            {"SearchResult": {"SearchResultItems": []}},
        ]
    )

    monkeypatch.setattr(ingestion_module, "fetch_page", fake_fetch)

    fake_insert = Mock()
    monkeypatch.setattr(ingestion_module, "insert_raw_page", fake_insert)

    run_id = ingestion_module.run_ingestion(
        tmp_path / "searches.yml",
        max_pages_per_search=5,
    )

    assert isinstance(run_id, str)
    assert fake_fetch.call_count == 2
    assert fake_insert.call_count == 2
    assert conn.commit.call_count == 2

    conn.rollback.assert_not_called()
    conn.close.assert_called_once()
    session.close.assert_called_once()


def test_run_ingestion_rolls_back_on_api_error(monkeypatch, tmp_path):
    search = ingestion_module.SearchConfig(
        name="data_engineer_orlando",
        keyword="data engineer",
        location="Orlando, FL",
    )

    conn = MagicMock()
    session = MagicMock()

    monkeypatch.setattr(ingestion_module, "load_searches", lambda _: [search])
    monkeypatch.setattr(
        ingestion_module,
        "build_usajobs_headers",
        lambda: {"Authenticated-Key": "fake-key"},
    )
    monkeypatch.setattr(ingestion_module, "pg_connect_local", lambda: conn)
    monkeypatch.setattr(ingestion_module.requests, "Session", lambda: session)

    fake_fetch = Mock(side_effect=requests.HTTPError("429 Too Many Requests"))
    monkeypatch.setattr(ingestion_module, "fetch_page", fake_fetch)

    fake_insert = Mock()
    monkeypatch.setattr(ingestion_module, "insert_raw_page", fake_insert)

    with pytest.raises(requests.HTTPError, match="429"):
        ingestion_module.run_ingestion(
            tmp_path / "searches.yml",
            max_pages_per_search=5,
        )

    fake_fetch.assert_called_once()
    fake_insert.assert_not_called()
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()
    session.close.assert_called_once()
