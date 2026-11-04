"""The version, app id and helper path are repeated in packaging files; keep them in sync."""
import re
import tomllib
import xml.etree.ElementTree as ET
from configparser import ConfigParser
from pathlib import Path

import kram

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def test_versions_match():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    spec = re.search(r"^%global base_version\s+(\S+)", (ROOT / "packaging/kram.spec").read_text(),
                     re.MULTILINE).group(1)
    metainfo = ET.parse(DATA / f"{kram.APP_ID}.metainfo.xml").find("releases/release").get("version")
    assert kram.__version__ == pyproject == spec == metainfo


def test_app_id_and_helper_path():
    desktop = ConfigParser(interpolation=None)
    desktop.optionxform = str
    desktop.read(DATA / f"{kram.APP_ID}.desktop", encoding="utf-8")
    assert desktop["Desktop Entry"]["Icon"] == kram.APP_ID
    assert (DATA / f"{kram.APP_ID}.svg").exists()
    assert ET.parse(DATA / f"{kram.APP_ID}.metainfo.xml").find("id").text == kram.APP_ID

    action = ET.parse(DATA / f"{kram.APP_ID}.policy").find("action")
    assert action.get("id") == kram.POLKIT_HELPER_ACTION
    exec_path = action.find("annotate[@key='org.freedesktop.policykit.exec.path']").text
    assert exec_path == kram.INSTALLED_HELPER
    assert "%{_libexecdir}/kram-helper" in (ROOT / "packaging/kram.spec").read_text()
    assert kram.INSTALLED_HELPER == "/usr/libexec/kram-helper"
