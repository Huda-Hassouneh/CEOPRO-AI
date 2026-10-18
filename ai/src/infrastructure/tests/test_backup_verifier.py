"""P2 (QA_TEST_STRATEGY.md): backup validator logic. docker/psql are mocked; no containers needed."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.database import backup_verifier as bv


@pytest.fixture
def validator(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "d")
    v = bv.BackupValidator()
    v.target_dir = str(tmp_path)
    v.snapshot_path = str(tmp_path / "snap.sql")
    return v


@pytest.mark.parametrize("missing", ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"])
def test_requires_all_postgres_settings(monkeypatch, missing):
    for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError):
        bv.BackupValidator()


def test_checksum_is_sha256_of_the_file(validator, tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"abc")
    assert validator._generate_file_checksum(str(f)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def _fake_dump(size):
    def run(cmd, stdout=None, **kw):
        stdout.write("x" * size)
    return run


def test_backup_succeeds_when_snapshot_is_big_enough(validator):
    with patch("subprocess.run", side_effect=_fake_dump(600)):
        assert validator.execute_backup_generation() is True


def test_backup_rejects_a_suspiciously_small_snapshot(validator):
    with patch("subprocess.run", side_effect=_fake_dump(100)):
        assert validator.execute_backup_generation() is False


def test_backup_reports_failure_when_pg_dump_fails(validator):
    err = subprocess.CalledProcessError(1, "docker", stderr=b"boom")
    with patch("subprocess.run", side_effect=err):
        assert validator.execute_backup_generation() is False


def test_restore_without_a_snapshot_fails_fast(validator):
    assert validator.validate_restoration_integrity() is False


def _restore(validator, tables):
    open(validator.snapshot_path, "w").write("x")
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (tables,)
    with patch("subprocess.run") as run, patch("psycopg2.connect", return_value=conn):
        result = validator.validate_restoration_integrity()
    return result, run


def test_restore_passes_with_enough_tables_and_drops_the_sandbox(validator):
    result, run = _restore(validator, bv.EXPECTED_TABLE_COUNT)
    assert result is True
    assert any("DROP DATABASE" in " ".join(c.args[0]) for c in run.call_args_list)


def test_restore_fails_with_too_few_tables_but_still_drops_the_sandbox(validator):
    result, run = _restore(validator, bv.EXPECTED_TABLE_COUNT - 1)
    assert result is False
    assert any("DROP DATABASE" in " ".join(c.args[0]) for c in run.call_args_list)
