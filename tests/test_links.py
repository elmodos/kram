"""Only web links leave Kram: a package's URL tag is written by whoever built the file."""
import pytest
from PySide6.QtCore import QUrl

from kram.qt import links


@pytest.mark.parametrize("url", ["file:///home/user/evil.desktop", "smb://server/share", "x-custom:run",
                                 "javascript:alert(1)", "ssh://host"])
def test_other_schemes_are_not_opened(monkeypatch, url):
    opened = []
    monkeypatch.setattr(links.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()) or True)
    assert links.open_web_link(QUrl(url)) is False
    assert opened == []


@pytest.mark.parametrize("url", ["https://example.org/project", "http://example.org/"])
def test_web_links_are_opened(monkeypatch, url):
    opened = []
    monkeypatch.setattr(links.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()) or True)
    links.open_web_link(QUrl(url))
    assert opened == [url]
