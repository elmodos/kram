"""The tray update checker: its state file, the tray's text, and that the long-lived tray stays light."""
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kram import notifier

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path


def test_state_round_trip(home):
    assert notifier.read_state() == {}
    notifier.write_state({"count": 3})
    assert notifier.read_state() == {"count": 3}
    assert notifier.state_file() == home / "cache" / "kram" / "update-check.json"


def test_stale_days_from_kram_settings(home):
    assert notifier.stale_days() == notifier.STALE_DAYS_DEFAULT
    conf = home / "config" / "kram" / "kram.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("[update_checker]\nstale_days=14\n")
    assert notifier.stale_days() == 14
    conf.write_text("[update_checker]\nstale_days=often\n")
    assert notifier.stale_days() == notifier.STALE_DAYS_DEFAULT


def test_tray_text(home):
    pytest.importorskip("gi.repository")
    from kram.notifier.tray import Tray

    tray = Tray.__new__(Tray)  # no D-Bus: only the text
    now = time.time()
    tray.state = {"count": 12, "severity": "high", "security": 2, "metadata_age": 3600, "checked_at": now}
    assert tray.icon() == "io.github.elmodos.Kram-update-high"
    assert tray.tooltip() == "12 updates available\n2 of them are security updates"
    tray.state = {"count": 1, "severity": "low", "security": 0, "metadata_age": 9 * 86400, "checked_at": now}
    assert tray.icon() == "io.github.elmodos.Kram-update-low"
    assert tray.tooltip() == "1 update available\nThe package information is 9 days old"


def test_kram_from_the_tray_gets_the_session_display():
    """A tray started before the desktop session told systemd its display: Kram takes it from the manager."""
    from kram.notifier.tray import launch_env
    own = {"PATH": "/usr/bin", "XDG_RUNTIME_DIR": "/run/user/1000"}
    manager = ["PATH=/usr/bin", "DISPLAY=:0", "WAYLAND_DISPLAY=wayland-0", "XAUTHORITY=/run/user/1000/xauth_x",
               "not a variable"]
    env = launch_env(own, manager, "token-1")
    assert env["DISPLAY"] == ":0" and env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["XAUTHORITY"] == "/run/user/1000/xauth_x" and env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["XDG_ACTIVATION_TOKEN"] == "token-1"
    assert "XDG_ACTIVATION_TOKEN" not in launch_env(own, [], "")
    assert launch_env(own, []) == own  # systemd did not answer: the tray's own environment


def test_tray_does_not_load_libdnf5_or_qt():
    pytest.importorskip("gi.repository")
    code = ("import sys; import kram.notifier.tray; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in ('libdnf5', 'PySide6', 'rpm')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_tray_icons_are_shipped():
    pytest.importorskip("gi.repository")
    from kram.notifier.tray import ICONS

    for name in ICONS.values():
        assert (ROOT / "data" / "icons" / f"{name}.svg").exists(), name


def test_tray_icon_path_holds_the_icons(monkeypatch):
    """The panel looks for the icons in IconThemePath too: a folder ending in "icons" with all three in it."""
    pytest.importorskip("gi.repository")
    from kram.notifier import tray

    assert tray.INSTALLED_ICON_DIR == "/usr/share/kram/icons"
    assert "%{_datadir}/kram/icons" in (ROOT / "packaging" / "kram.spec").read_text()
    monkeypatch.setattr(tray, "INSTALLED_ICON_DIR", "/nonexistent/kram/icons")  # the source checkout's folder
    folder = Path(tray.icon_dir())
    assert folder.name == "icons"
    for name in tray.ICONS.values():
        assert (folder / f"{name}.svg").exists(), name


def test_units_start_existing_modules():
    for unit in (ROOT / "data" / "systemd").iterdir():
        for line in unit.read_text().splitlines():
            if line.startswith("ExecStart="):
                module = line.split(" -m ")[1].split()[0]
                assert (ROOT / (module.replace(".", "/") + ".py")).exists(), line


@pytest.fixture
def autostart(tmp_path, monkeypatch, home):
    from kram.notifier import control

    system = tmp_path / "xdg-autostart"
    system.mkdir()
    (system / "org.kde.discover.notifier.desktop").write_text("[Desktop Entry]\nExec=DiscoverNotifier\n")
    monkeypatch.setattr(control, "SYSTEM_AUTOSTART", system)
    return home / "config" / "autostart"


def test_notifier_turned_off_and_on(autostart):
    from kram.notifier.control import NOTIFIERS

    discover, gnome = NOTIFIERS
    assert gnome.system_file() is None  # not installed: the dialog shows no row for it
    assert not discover.turned_off()
    discover.turn_off()
    override = autostart / "org.kde.discover.notifier.desktop"
    assert "Hidden=true" in override.read_text().splitlines()
    assert discover.turned_off()
    discover.turn_on()
    assert not override.exists() and not discover.turned_off()


def test_notifier_override_of_the_user_is_not_ours(autostart):
    from kram.notifier.control import NOTIFIERS

    autostart.mkdir(parents=True)
    (autostart / "org.kde.discover.notifier.desktop").write_text("[Desktop Entry]\nExec=my-own-notifier\n")
    assert not NOTIFIERS[0].turned_off()  # a file the user wrote, not a turned-off notifier


@pytest.mark.parametrize("answer, state", [("enabled", "enabled"), ("static", "enabled"), ("disabled", "disabled"),
                                           ("masked", "disabled"), ("", "missing"), ("not-found", "missing")])
def test_fedora_timer_state(monkeypatch, answer, state):
    from kram.notifier import control

    monkeypatch.setattr(control, "_systemctl", lambda *a, **k: subprocess.CompletedProcess(a, 0, answer + "\n", ""))
    assert control.fedora_timer_state() == state


@pytest.mark.parametrize("enabled", [True, False])
def test_recheck_only_when_the_checker_is_on(monkeypatch, enabled):
    from kram.notifier import control

    calls = []

    def systemctl(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0 if enabled else 1, "", "")
    monkeypatch.setattr(control, "_systemctl", systemctl)
    control.recheck()
    started = ("--user", "start", "--no-block", control.CHECK_SERVICE)
    assert (started in calls) is enabled  # never shows the icon of a checker the user turned off


def test_notifier_dialog(monkeypatch, autostart):
    pytest.importorskip("PySide6.QtWidgets")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from kram.notifier import control
    from kram.ui import notifier_dialog

    QApplication.instance() or QApplication([])
    calls = []
    monkeypatch.setattr(control, "checker_enabled", lambda: bool(calls) and calls[-1])
    monkeypatch.setattr(control, "set_checker_enabled", lambda on: calls.append(on) or "")
    monkeypatch.setattr(control, "fedora_timer_state", lambda: "disabled")
    dialog = notifier_dialog.NotifierDialog()
    assert not dialog.fedora_button.isHidden()
    assert not dialog.stale_row.isEnabled()
    dialog.enabled.setChecked(True)
    assert calls == [True] and dialog.stale_row.isEnabled()
    [row] = dialog.rows  # Discover only: GNOME Software is not "installed"
    monkeypatch.setattr(notifier_dialog, "_bus_owner_pid", lambda name: None)
    row.toggle.click()
    assert row.notifier.turned_off() and row.toggle.text() == "Turn Back On"
    row.toggle.click()
    assert not row.notifier.turned_off()


def test_notifier_dialog_rereads_on_activation(monkeypatch, autostart):
    """The user may delete the override in the file manager the dialog opened, or turn things on elsewhere."""
    pytest.importorskip("PySide6.QtWidgets")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    from kram.notifier import control
    from kram.ui import notifier_dialog

    QApplication.instance() or QApplication([])
    enabled = [False]
    monkeypatch.setattr(control, "checker_enabled", lambda: enabled[0])
    monkeypatch.setattr(control, "set_checker_enabled", lambda on: pytest.fail("not the user's click"))
    monkeypatch.setattr(control, "fedora_timer_state", lambda: "enabled")
    monkeypatch.setattr(notifier_dialog, "_bus_owner_pid", lambda name: None)
    dialog = notifier_dialog.NotifierDialog()
    [row] = dialog.rows
    row.toggle.click()
    assert row.toggle.text() == "Turn Back On"
    row.notifier.override().unlink()  # deleted by hand
    enabled[0] = True                 # turned on in a terminal
    QApplication.sendEvent(dialog, QEvent(QEvent.Type.WindowActivate))
    assert row.toggle.text() == "Turn Off"
    assert dialog.enabled.isChecked() and dialog.stale_row.isEnabled()


def test_update_check_counts_again_after_a_kram_upgrade(home, monkeypatch):
    from kram import __version__
    from kram.notifier import check

    fp = [["/var/lib/rpm/rpmdb.sqlite", 1]]
    monkeypatch.setattr(check, "fingerprint", lambda: fp)
    monkeypatch.setattr(check, "systemctl", lambda verb: None)
    counts = []
    monkeypatch.setattr(check, "count", lambda: counts.append(1) or {"count": 0, "severity": "low", "seconds": 0.1})

    notifier.write_state({"count": 3, "severity": "low", "fingerprint": fp, "version": "0.1.0"})
    check.main()
    assert counts == [1] and notifier.read_state()["version"] == __version__
    check.main()  # nothing changed since
    assert counts == [1]


def test_a_systemctl_timeout_is_a_failed_command(monkeypatch):
    from kram.notifier import control

    def hangs(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(control.subprocess, "run", hangs)
    assert control.checker_enabled() is False
    assert control.set_checker_enabled(True) == "timeout"


def test_repository_changes_outside_yum_repos_d_are_noticed(tmp_path, monkeypatch):
    from kram.notifier import check

    roots = {"override": tmp_path / "override.d", "distro": tmp_path / "distro.d",
             "distro2": tmp_path / "distro2.d", "libdnf": tmp_path / "libdnf.d"}
    for root in roots.values():
        root.mkdir()
    monkeypatch.setattr(check, "WATCHED", [str(roots["override"] / "*.repo"), str(roots["distro"] / "*.repo"),
                                           str(roots["distro2"] / "*.repo"), str(roots["libdnf"] / "*")])
    before = check.fingerprint()
    for root, name in ((roots["override"], "99-config_manager.repo"), (roots["distro"], "fedora.repo"),
                       (roots["distro2"], "fedora-updates.repo"), (roots["libdnf"], "10-proxy.conf")):
        (root / name).write_text("x")
        assert check.fingerprint() != before, root
        before = check.fingerprint()


def test_the_checker_watches_the_repository_locations():
    from kram.notifier import check

    for pattern in ("/etc/dnf/repos.override.d/*.repo", "/usr/share/dnf5/repos.d/*.repo",
                    "/etc/distro.repos.d/*.repo", "/etc/dnf/libdnf5.conf.d/*"):
        assert pattern in check.WATCHED
