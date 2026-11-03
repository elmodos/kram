from dnf_gui.core.model import Origin
from dnf_gui.core.origin import classify, display_repo


def test_classify():
    assert classify("fedora") is Origin.FEDORA
    assert classify("updates") is Origin.FEDORA
    assert classify("6ecc2dfaa0dc41e5ad51e007707a786b") is Origin.FEDORA  # installer media
    assert classify("copr:copr.fedorainfracloud.org:wezfurlong:wezterm-nightly") is Origin.COPR
    assert classify("@commandline") is Origin.LOCAL
    assert classify("<unknown>") is Origin.UNKNOWN
    assert classify("") is Origin.UNKNOWN
    assert classify("rpmfusion-free") is Origin.THIRD_PARTY


def test_display_repo():
    assert display_repo("copr:copr.fedorainfracloud.org:wezfurlong:wezterm-nightly") == "wezfurlong/wezterm-nightly"
    assert display_repo("fedora") == "fedora"
