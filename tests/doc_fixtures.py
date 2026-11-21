"""Inputs for the HTML characterization of the detail tabs, the empty list and What's New (tests/test_doc.py):
the HTML Kram 0.11.3 made of them is in tests/data/html_0.11.3.json, and the document model must render the same."""
from kram.core.model import (
                    Advisory,
                    ChangelogEntry,
                    Origin,
                    PkgDetails,
                    PkgRow,
                    Reason,
                    Status,
                    VersionInfo,
                    VersionLock,
)
from kram.core.releases import Release

CRITICAL = Advisory("FEDORA-2026-1a2b", "security", "critical", "firefox 149 & <friends>", 1780000000,
                    "Security fixes:\n- CVE-2026-1 \"quoted\"\n- O'Brien's bug", (
                        ("cve", "CVE-2026-1", "https://cve.org/CVE-2026-1"),
                        ("bugzilla", "2369081", "https://bugzilla.redhat.com/2369081"),
                        ("bugzilla", "x1", ""), ("other", "", "https://example.org/a?b=1&c=2")))
BUGFIX = Advisory("FEDORA-2026-3c4d", "bugfix", "", "", 0)
NEWPACKAGE = Advisory("RHSA-2026:6", "newpackage", "", "New package", 1780000000)

ROWS = {
    "advisories": PkgRow("firefox", "x86_64", "Web browser", "148-1.fc45", "149-1.fc45", "updates", 1, Origin.FEDORA,
                         Status.UPGRADABLE, True, "updates", Reason.USER, advisories=(CRITICAL, BUGFIX, NEWPACKAGE)),
    "held": PkgRow("lockme", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.COPR, Status.INSTALLED, True,
                   "copr:copr.fedorainfracloud.org:owner:proj", Reason.DEPENDENCY,
                   locks=(VersionLock("evr = 1-1", "Added by 'versionlock add' <me>"), VersionLock("arch = x86_64")),
                   held_evr="2-1", held_advisories=(BUGFIX,)),
    "plain": PkgRow("bash", "x86_64", "The shell", "5.3-1", "5.3-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED),
}

BLOCKED = [
    "Problem: package ffmpeg-9.0.2-4.fc45.x86_64 from rpmfusion requires ffmpeg-libs = 9.0.2-4.fc45, but none of the "
    "providers can be installed\n  - nothing provides liboapv.so.11()(64bit) needed by ffmpeg-libs <x86_64> & co\n",
    "",
]

DETAILS = {
    "full": PkgDetails(
        "firefox-149-1.fc45.x86_64", "Mozilla <Firefox> & co", "First paragraph with 'quotes'.\n\nSecond\nline.\n\n  ",
        "https://www.mozilla.org/?a=1&b=2", "MPL-2.0", "Fedora Project", "Fedora <packager@fedoraproject.org>",
        "firefox-149-1.fc45.src.rpm", 1780000000, 1780100000, "updates", "updates", 250_000_000, 80_000_000, True,
        ["libc.so.6()(64bit)", "gtk3 >= 3.24"], ["mozilla-openh264"], [], [f"cap{i} = 1" for i in range(1003)],
        ["firefox-old < 2"], [], [("thunderbird", "x86_64"), ("gnome-shell", "x86_64")], ["/usr/bin/firefox"], True,
        [ChangelogEntry(1780000000, "Jane Doe <jane@example.org> - 149-1", "- Update to 149\n- Fix <bug> & more"),
         ChangelogEntry(1770000000, "John", "- Older")],
        [VersionInfo("149-1.fc45", "updates", candidate=True), VersionInfo("148-1.fc45", "@System", installed=True),
         VersionInfo("150-1.fc45", "updates-testing", locked_out=True)]),
    "bare": PkgDetails(
        "tiny-1-1.noarch", "", "", "", "", "", "", "tiny-1-1.src.rpm", 0, None, "", "", 10, None, None,
        [], [], [], [], [], [], [], [], False, [], []),
}

EMPTY = [
    dict(filter="Installed", in_all=False),
    dict(filter="Locked versions", in_all=False, hint="Select a package & lock it: <here>."),
    dict(filter="COPR <owner>", in_all=False, text="vlc & <b>", found_in_all=3),
    dict(filter="All", in_all=True, text="playlists", found_in_descriptions=1),
    dict(filter="All", in_all=True, text="libfoo.so", file_search=True, missing_repos=2),
    dict(filter="Upgradable", in_all=False, text="x", found_in_all=1, missing_repos=1),
]

RELEASES = [Release("0.11.3", "2026-11-20", ["Intro & <more>."], ["One", "Two <b>"]),
            Release("0.0.1", "2026-01-01", [], ["First"]), Release("0.0.0", "2025-12-31", ["Only text."], [])]
