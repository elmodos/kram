"""kram.core.settings reads and writes kram.conf the way QSettings does, and the two do not lose each other's keys."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from kram.core import settings
from kram.core.settings import Settings, escape_string, parse, unescape_value

VALUES = [
    "plain", "", " leading", "trailing ", "a, b", "semi;colon", "key=value", 'say "hi"', "back\\slash",
    "Пошук пакетів", "tab\there", "line\nbreak", "@at", "@@two", "50%", "ünï ✓ 𝄞", "\x01control",
    json.dumps([["vim", 0, 3], ["вім", 1, 5]], ensure_ascii=False), "#hash", "[bracket]",
]


def test_strings_round_trip_through_the_escaping():
    for value in VALUES:
        assert unescape_value(escape_string(settings._prefixed(value))) in (value, "@" + value), value
        store_text = settings.format_value(value)
        assert settings._variant_text(unescape_value(store_text)) == value


def test_values_round_trip(tmp_path):
    s = Settings(tmp_path / "kram.conf")
    for i, value in enumerate(VALUES):
        s.set(f"strings/v{i}", value)
    s.set("numbers/int", 42)
    s.set("numbers/negative", -7)
    s.set("numbers/float", 1.5)
    s.set("flags/on", True)
    s.set("flags/off", False)
    s.set("top", "level")
    fresh = Settings(tmp_path / "kram.conf")
    assert [fresh.get(f"strings/v{i}") for i in range(len(VALUES))] == VALUES
    assert fresh.get("numbers/int", 0) == 42 and fresh.get("numbers/negative", type=int) == -7
    assert fresh.get("numbers/float", 0.0) == 1.5
    assert fresh.get("flags/on", False) is True and fresh.get("flags/off", True) is False
    assert fresh.get("top") == "level"
    assert "[General]\ntop=level\n" in (tmp_path / "kram.conf").read_text()


def test_defaults_and_bad_values(tmp_path):
    conf = tmp_path / "kram.conf"
    conf.write_text("[a]\nn=often\nb=0\nempty=\nbytes=@ByteArray(\\0\\x1)\nlist=x, y\n")
    s = Settings(conf)
    assert s.get("a/missing", 7) == 7 and s.get("a/missing") is None
    assert s.get("a/n", 3) == 3  # not a number: the default
    assert s.get("a/b", True) is False and s.get("a/empty", True) is False
    assert s.get("a/bytes", "x") == "x"  # only Qt can read it
    assert s.get("a/list") == "x, y" and s.get("a/list", type=list) == ["x", "y"]


def test_unknown_keys_survive_byte_for_byte(tmp_path):
    conf = tmp_path / "kram.conf"
    blob = '@ByteArray(\\x1\\xd9\\xd0\\xcb\\0\\x3\\0\\0\\0\\0\\0\\0\\0\\0\\0\\0\\0\\0\\x5\\x1f)'
    conf.write_text(f"[General]\nfoo=1\n\n[window]\ngeometry={blob}\nhsplit=@ByteArray(abc)\n\n"
                    "[search]\nmode=2\n")
    s = Settings(conf)
    s.set("search/mode", 3)
    s.set("search/history", "[]")
    s.remove("General/missing")
    text = conf.read_text()
    assert f"geometry={blob}\n" in text and "hsplit=@ByteArray(abc)\n" in text
    assert parse(text) == {"foo": "1", "window/geometry": blob, "window/hsplit": "@ByteArray(abc)",
                           "search/mode": "3", "search/history": "[]"}
    s.remove("search/mode")
    assert not s.contains("search/mode") and s.contains("window/geometry")


def test_comments_quotes_and_continuations(tmp_path):
    conf = tmp_path / "kram.conf"
    conf.write_text('; a comment\n[s]\na = "quoted ; not a comment" ; a comment\nb=one \\\n two\n'
                    'c="spans\nlines"\n%General\\x=1\n')
    s = Settings(conf)
    assert s.get("s/a") == "quoted ; not a comment"
    assert s.get("s/b") == "one  two"
    assert s.get("s/c") == "spans\nlines"


def test_a_file_that_changed_is_read_again(tmp_path):
    conf = tmp_path / "kram.conf"
    s = Settings(conf)
    s.set("a/b", 1)
    conf.write_text("[a]\nb=22\n")
    assert s.get("a/b", 0) == 22


def test_the_default_path_follows_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.store.set("x/y", "z")
    assert (tmp_path / "kram" / "kram.conf").read_text() == "[x]\ny=z\n"


def test_a_stale_lock_is_taken_over(tmp_path):
    conf = tmp_path / "kram.conf"
    (tmp_path / "kram.conf.lock").write_text("999999999\nkram\nhost\n")  # no such process, nobody holds it
    Settings(conf).set("a/b", 1)
    assert conf.exists() and not (tmp_path / "kram.conf.lock").exists()


# ---------------------------------------------------------------- with QSettings

def qt_run(conf: Path, code: str) -> str:
    """Run `code` with a QSettings `s` on `conf`, in a process of its own (as the GUI process would be)."""
    script = textwrap.dedent("""
        import json, sys
        from PySide6.QtCore import QSettings
        s = QSettings(sys.argv[1], QSettings.Format.IniFormat)
    """) + textwrap.dedent(code)
    result = subprocess.run([sys.executable, "-c", script, str(conf)], capture_output=True, text=True, check=True)
    return result.stdout


@pytest.fixture
def qt():
    pytest.importorskip("PySide6.QtCore")
    return qt_run


def test_qsettings_reads_what_the_store_writes(tmp_path, qt):
    conf = tmp_path / "kram.conf"
    s = Settings(conf)
    for i, value in enumerate(VALUES):
        s.set(f"strings/v{i}", value)
    s.set("numbers/int", 42)
    s.set("flags/on", True)
    s.set("flags/off", False)
    s.set("top", "level")
    out = qt(conf, f"""
        values = [s.value(f"strings/v{{i}}") for i in range({len(VALUES)})]
        print(json.dumps([values, s.value("numbers/int", 0, type=int), s.value("flags/on", False, type=bool),
                          s.value("flags/off", True, type=bool), s.value("top")]))
    """)
    assert json.loads(out) == [VALUES, 42, True, False, "level"]


def test_the_store_reads_what_qsettings_writes(tmp_path, qt):
    conf = tmp_path / "kram.conf"
    qt(conf, f"""
        for i, value in enumerate({VALUES!r}):
            s.setValue(f"strings/v{{i}}", value)
        s.setValue("numbers/int", 42)
        s.setValue("numbers/float", 2.25)
        s.setValue("flags/on", True)
        s.setValue("flags/off", False)
        s.setValue("top", "level")
        s.setValue("General/x", "general section")
        s.sync()
    """)
    s = Settings(conf)
    assert [s.get(f"strings/v{i}") for i in range(len(VALUES))] == VALUES
    assert s.get("numbers/int", 0) == 42 and s.get("numbers/float", 0.0) == 2.25
    assert s.get("flags/on", False) is True and s.get("flags/off", True) is False
    assert s.get("top") == "level" and s.get("General/x") == "general section"


def test_a_qt_bytearray_survives_a_store_write(tmp_path, qt):
    conf = tmp_path / "kram.conf"
    qt(conf, """
        s.setValue("window/geometry", bytes(range(256)))
        s.setValue("search/mode", 1)
        s.sync()
    """)
    Settings(conf).set("search/mode", 2)
    Settings(conf).set("search/history", '["vim"]')
    out = qt(conf, """
        print(json.dumps([list(bytes(s.value("window/geometry"))), s.value("search/mode", type=int),
                          s.value("search/history")]))
    """)
    assert json.loads(out) == [list(range(256)), 2, '["vim"]']


def test_both_writers_keep_each_others_keys(tmp_path, qt):
    """The Qt front end keeps a QSettings for its own keys while the store writes the shared ones: a QSettings that
    read the file before the store wrote merges only its own changes when it syncs."""
    conf = tmp_path / "kram.conf"
    script = tmp_path / "store.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
        from kram.core.settings import Settings
        Settings(sys.argv[1]).set(sys.argv[2], sys.argv[3])
    """))
    out = qt(conf, f"""
        import os, subprocess, time
        s.setValue("window/geometry", b"\\x01\\x02")
        s.sync()
        value = s.value("window/geometry")  # read: QSettings now holds the file in memory
        time.sleep(0.01)
        subprocess.run([sys.executable, {str(script)!r}, sys.argv[1], "search/mode", "4"], check=True)
        s.setValue("window/hsplit", b"\\x03")  # a Qt-only key changed after the store wrote
        s.sync()
        subprocess.run([sys.executable, {str(script)!r}, sys.argv[1], "sidebar/view", "origin"], check=True)
        s.setValue("table/header-v2", b"\\x04")
        s.sync()
        print(json.dumps([s.value("search/mode"), s.value("sidebar/view")]))
    """)
    assert json.loads(out) == ["4", "origin"]
    s = Settings(conf)
    assert s.get("search/mode", 0) == 4 and s.get("sidebar/view") == "origin"
    raw = parse(conf.read_text())
    assert {"window/geometry", "window/hsplit", "table/header-v2"} <= raw.keys()


def test_concurrent_writes_from_both_keep_every_key(tmp_path, qt):
    conf = tmp_path / "kram.conf"
    root = str(Path(__file__).resolve().parent.parent)
    store = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {root!r})
        from kram.core.settings import Settings
        s = Settings(sys.argv[1])
        for i in range(60):
            s.set(f"store/k{{i}}", i)
    """), str(conf)])
    qt(conf, """
        for i in range(60):
            s.setValue(f"qt/k{i}", i)
            s.sync()
    """)
    assert store.wait(30) == 0
    raw = parse(conf.read_text())
    assert {f"store/k{i}" for i in range(60)} <= raw.keys()
    assert {f"qt/k{i}" for i in range(60)} <= raw.keys()


def test_a_kram_conf_from_0_11_3_reads_the_same(tmp_path):
    """A real kram.conf written by Kram 0.11.3 (QSettings), with the user's values replaced by harmless ones."""
    conf = tmp_path / "kram.conf"
    fixture = Path(__file__).with_name("data") / "kram-0.11.3.conf"
    conf.write_bytes(fixture.read_bytes())
    s = Settings(conf)
    assert s.get("search/mode", 0) == 1
    assert json.loads(s.get("search/history", "[]"))[0] == ["firefox", 0, 4]
    assert s.get("sidebar/view") == "status" and s.get("sidebar/entry") == "status:upgradable"
    assert s.get("details/tab-name") == "dependencies" and s.get("details/files-view") == "tree"
    assert s.get("table/status_click", True) is False and s.get("distro/watch", False) is True
    assert s.get("distro/target", 0) == 45 and s.get("distro/running_eol") == "2027-06-02"
    assert s.get("toolbar/style") == "system" and s.get("progress/auto_close", True) is False
    assert s.get("update_checker/stale_days", 7) == 14
    assert s.get("markings/dir") == "/home/user/Документи"
    filters = json.loads(s.get("filters/custom", "[]"))
    assert filters[0]["name"] == "Big, slow; =ones"
    before = os.stat(conf).st_size
    s.set("search/mode", 1)  # no change: the file is left alone
    assert os.stat(conf).st_size == before
