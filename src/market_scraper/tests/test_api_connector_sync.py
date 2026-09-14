"""
Offline tests for api_connector_sync.py's own request-building logic -
no DB, no real HTTP call. httpx.get is monkeypatched throughout, same
convention as test_connector_sync_integration_db.py's psycopg2.connect
mocking for the client-side connection: real network calls to an
arbitrary vendor's API are not something a unit test should ever attempt.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.market_scraper.api_connector_sync import _get_nested, build_api_fetch_page


def _fake_response(json_body, status_ok=True):
    response = MagicMock()
    response.json.return_value = json_body
    if status_ok:
        response.raise_for_status = MagicMock()
    else:
        import httpx
        response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("boom", request=None, response=response))
    return response


def test_get_nested_returns_the_payload_itself_when_no_path_given():
    payload = [{"a": 1}]
    assert _get_nested(payload, None) is payload
    assert _get_nested(payload, "") is payload


def test_get_nested_walks_a_dotted_path():
    payload = {"data": {"results": [{"a": 1}]}}
    assert _get_nested(payload, "data.results") == [{"a": 1}]


def test_get_nested_returns_none_for_a_missing_path():
    assert _get_nested({"data": {}}, "data.results") is None
    assert _get_nested({"other": []}, "data.results") is None


def test_fetch_page_returns_bare_array_response():
    config = {"base_url": "https://pos.example.com/sales", "field_mapping": {}}
    fetch_page = build_api_fetch_page(config, credentials={})
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response([{"sku": "A"}])) as mock_get:
        records = fetch_page(1)
    assert records == [{"sku": "A"}]
    assert mock_get.call_args.kwargs["params"] == {"page": 1}


def test_fetch_page_extracts_records_via_records_path():
    config = {"base_url": "https://pos.example.com/sales", "field_mapping": {}, "records_path": "data.results"}
    fetch_page = build_api_fetch_page(config, credentials={})
    body = {"data": {"results": [{"sku": "A"}, {"sku": "B"}]}}
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response(body)):
        records = fetch_page(1)
    assert records == [{"sku": "A"}, {"sku": "B"}]


def test_fetch_page_returns_none_on_an_empty_page_stopping_pagination():
    config = {"base_url": "https://pos.example.com/sales", "field_mapping": {}}
    fetch_page = build_api_fetch_page(config, credentials={})
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response([])):
        assert fetch_page(1) is None


def test_fetch_page_raises_on_a_non_list_records_path_result():
    config = {"base_url": "https://pos.example.com/sales", "field_mapping": {}, "records_path": "data"}
    fetch_page = build_api_fetch_page(config, credentials={})
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response({"data": {"not": "a list"}})):
        with pytest.raises(ValueError, match="expected a list"):
            fetch_page(1)


def test_fetch_page_builds_bearer_auth_header_from_credentials():
    config = {"base_url": "https://pos.example.com/sales", "field_mapping": {}}
    fetch_page = build_api_fetch_page(config, credentials={"api_key": "secret-token"})
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response([])) as mock_get:
        fetch_page(1)
    assert mock_get.call_args.kwargs["headers"] == {"Authorization": "Bearer secret-token"}


def test_fetch_page_supports_a_custom_auth_header_and_scheme():
    config = {
        "base_url": "https://pos.example.com/sales", "field_mapping": {},
        "auth_header": "X-Api-Key", "auth_scheme": "",
    }
    fetch_page = build_api_fetch_page(config, credentials={"token": "abc123"})
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response([])) as mock_get:
        fetch_page(1)
    assert mock_get.call_args.kwargs["headers"] == {"X-Api-Key": "abc123"}


def test_fetch_page_sends_no_auth_header_when_no_credentials_given():
    config = {"base_url": "https://pos.example.com/sales", "field_mapping": {}}
    fetch_page = build_api_fetch_page(config, credentials={})
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response([])) as mock_get:
        fetch_page(1)
    assert mock_get.call_args.kwargs["headers"] == {}


def test_fetch_page_includes_extra_query_params_and_page_size():
    config = {
        "base_url": "https://pos.example.com/sales", "field_mapping": {},
        "page_size_param": "per_page", "page_size": 50,
        "extra_query_params": {"store_id": "42"},
    }
    fetch_page = build_api_fetch_page(config, credentials={})
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response([])) as mock_get:
        fetch_page(3)
    assert mock_get.call_args.kwargs["params"] == {"page": 3, "per_page": 50, "store_id": "42"}


def test_fetch_page_propagates_a_real_http_error():
    config = {"base_url": "https://pos.example.com/sales", "field_mapping": {}}
    fetch_page = build_api_fetch_page(config, credentials={})
    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_response({}, status_ok=False)):
        with pytest.raises(Exception):
            fetch_page(1)
