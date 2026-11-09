from pathlib import Path

import pytest

from . import test_custom_self_service_browser as browser


def test_explicit_browser_is_used(monkeypatch, tmp_path):
    executable = tmp_path / 'chromium'
    executable.touch()
    monkeypatch.setenv('CHROMIUM_PATH', str(executable))
    assert browser.browser_executable() == executable


def test_invalid_explicit_browser_fails_instead_of_skipping(monkeypatch, tmp_path):
    monkeypatch.setenv('CHROMIUM_PATH', str(tmp_path / 'missing'))
    with pytest.raises(AssertionError, match='CHROMIUM_PATH'):
        browser.browser_executable()


@pytest.mark.parametrize('name', ['google-chrome', 'chromium', 'chromium-browser'])
def test_browser_discovery_on_path(monkeypatch, name):
    monkeypatch.delenv('CHROMIUM_PATH', raising=False)
    monkeypatch.setattr(browser.shutil, 'which', lambda candidate: '/usr/bin/' + name if candidate == name else None)
    assert browser.browser_executable() == Path('/usr/bin/' + name)


def test_missing_browser_fails_instead_of_skipping(monkeypatch):
    monkeypatch.delenv('CHROMIUM_PATH', raising=False)
    monkeypatch.setattr(browser.shutil, 'which', lambda _: None)
    monkeypatch.setattr(browser.Path, 'is_file', lambda _: False)
    with pytest.raises(AssertionError, match='Install Chrome'):
        browser.browser_executable()
