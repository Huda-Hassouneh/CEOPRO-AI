import json
from unittest.mock import MagicMock, patch

import pytest

from src.market_scraper.policy_cli import main


def run_cli(argv):
    with patch("sys.argv", ["policy_cli.py"] + argv):
        main()


def test_no_subcommand_is_rejected():
    with patch("sys.argv", ["policy_cli.py"]):
        with pytest.raises(SystemExit):
            main()


def test_set_credentials_inline_json_writes_via_data_access(capsys):
    fake_conn = MagicMock()
    with patch("src.market_scraper.policy_cli.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.policy_cli.data_access.set_source_credentials") as mocked_set:
        run_cli([
            "set-credentials", "--tenant-id", "t1", "--source-id", "s1",
            "--credentials", '{"api_token": "apify-token-123"}',
        ])

    mocked_set.assert_called_once_with(fake_conn, "t1", "s1", {"api_token": "apify-token-123"})
    fake_conn.close.assert_called_once()
    assert "api_token" in capsys.readouterr().out


def test_set_credentials_from_file(tmp_path, capsys):
    credentials_file = tmp_path / "creds.json"
    credentials_file.write_text('{"client_id": "abc", "client_secret": "xyz"}')
    fake_conn = MagicMock()
    with patch("src.market_scraper.policy_cli.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.policy_cli.data_access.set_source_credentials") as mocked_set:
        run_cli([
            "set-credentials", "--tenant-id", "t1", "--source-id", "s1",
            "--credentials-file", str(credentials_file),
        ])

    mocked_set.assert_called_once_with(fake_conn, "t1", "s1", {"client_id": "abc", "client_secret": "xyz"})


def test_set_credentials_rejects_malformed_json():
    fake_conn = MagicMock()
    with patch("src.market_scraper.policy_cli.data_access.get_tenant_connection", return_value=fake_conn):
        with pytest.raises(SystemExit):
            run_cli(["set-credentials", "--tenant-id", "t1", "--source-id", "s1", "--credentials", "not json"])


def test_set_credentials_rejects_a_json_array_not_an_object():
    fake_conn = MagicMock()
    with patch("src.market_scraper.policy_cli.data_access.get_tenant_connection", return_value=fake_conn):
        with pytest.raises(SystemExit):
            run_cli(["set-credentials", "--tenant-id", "t1", "--source-id", "s1", "--credentials", "[1, 2, 3]"])


def test_set_credentials_requires_exactly_one_of_credentials_or_file():
    with pytest.raises(SystemExit):
        run_cli(["set-credentials", "--tenant-id", "t1", "--source-id", "s1"])


def test_set_credentials_surfaces_a_source_not_found_error():
    fake_conn = MagicMock()
    with patch("src.market_scraper.policy_cli.data_access.get_tenant_connection", return_value=fake_conn), \
         patch(
             "src.market_scraper.policy_cli.data_access.set_source_credentials",
             side_effect=ValueError("source not found for this tenant"),
         ):
        with pytest.raises(SystemExit):
            run_cli(["set-credentials", "--tenant-id", "t1", "--source-id", "s1", "--credentials", "{}"])
    fake_conn.close.assert_called_once()  # connection still closed even when the write fails


def test_register_source_still_works_as_a_subcommand(capsys):
    fake_conn = MagicMock()
    with patch("src.market_scraper.policy_cli.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.policy_cli.data_access.record_policy_decision") as mocked_record:
        run_cli([
            "register-source", "--tenant-id", "t1", "--source-id", "s1",
            "--source-url", "https://books.toscrape.com/", "--public-web",
            "--terms-permit", "yes", "--technical-controls-permit", "yes",
            "--approval-reference", "reviewed manually", "--approved-by", "reviewer-uuid",
        ])

    mocked_record.assert_called_once()
    assert "ALLOWED" in capsys.readouterr().out
