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
    # file managers offer "Open with Kram" for packages, which opens only the installer
    assert desktop["Desktop Entry"]["Exec"] == "kram %f"
    assert "application/x-rpm" in desktop["Desktop Entry"]["MimeType"].split(";")
    assert (DATA / f"{kram.APP_ID}.svg").exists()
    assert ET.parse(DATA / f"{kram.APP_ID}.metainfo.xml").find("id").text == kram.APP_ID

    action = ET.parse(DATA / f"{kram.APP_ID}.policy").find("action")
    assert action.get("id") == kram.POLKIT_HELPER_ACTION
    exec_path = action.find("annotate[@key='org.freedesktop.policykit.exec.path']").text
    assert exec_path == kram.INSTALLED_HELPER
    assert "%{_libexecdir}/kram-helper" in (ROOT / "packaging/kram.spec").read_text()
    assert kram.INSTALLED_HELPER == "/usr/libexec/kram-helper"


def _desktop_entry(name):
    desktop = ConfigParser(interpolation=None)
    desktop.optionxform = str
    desktop.read(DATA / name, encoding="utf-8")
    return desktop["Desktop Entry"]


def test_xfce_settings_entry():
    main = _desktop_entry(f"{kram.APP_ID}.desktop")
    xfce = _desktop_entry(f"{kram.APP_ID}.xfce-settings.desktop")
    # the Xfce Settings Manager shows an entry only with both categories; the section is System
    categories = xfce["Categories"].split(";")
    assert {"Settings", "X-XFCE-SettingsDialog", "X-XFCE-SystemSettings"} <= set(categories)
    # Settings would take Kram out of the System menus elsewhere (Plasma's System Tools excludes it)
    assert xfce["OnlyShowIn"] == "XFCE;"
    assert "MimeType" not in xfce and xfce["Exec"] == "kram"  # the main file opens .rpm files
    # labelled with the main entry's GenericName, in every language; the same icon and other translations
    labels = {k.replace("GenericName", "Name", 1): v for k, v in main.items() if k.startswith("GenericName")}
    assert {k: v for k, v in xfce.items() if k.split("[")[0] in ("Name", "GenericName")} == labels
    same = [k for k in main if k.split("[")[0] in ("Comment", "Keywords", "Icon")]
    assert {k: xfce.get(k) for k in same} == {k: main[k] for k in same}


def test_readme_lists_every_translation():
    readme = (ROOT / "README.md").read_text()
    codes = sorted(p.stem for p in (ROOT / "po").glob("*.po"))
    assert f"translations-{len(codes) + 1}%20languages" in readme  # + English
    listed = sorted(re.findall(r"^\| [^|]+ \| [^|]+ \| `([a-zA-Z_]+)` \|", readme, re.MULTILINE))
    assert listed == codes
