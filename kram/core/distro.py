"""Which Fedora runs here, and is a newer one out? No Qt, no libdnf5, no network: the callers fetch."""
import shutil
from collections.abc import Callable
from dataclasses import dataclass

# Bodhi is what Fedora's own release tooling reads; its `state` says which releases have shipped
BODHI_RELEASES_URL = "https://bodhi.fedoraproject.org/releases/?rows_per_page=100&exclude_archived=true"
UPGRADE_GUIDE_URL = "https://docs.fedoraproject.org/en-US/quick-docs/upgrading-fedora-offline/"
RELEASE_NOTES_URL = "https://docs.fedoraproject.org/en-US/fedora/f{version}/release-notes/"
OS_RELEASE_PATHS = ("/etc/os-release", "/usr/lib/os-release")
MAX_RELEASE_JUMP = 2  # the longest upgrade Fedora supports


@dataclass(frozen=True, slots=True)
class FedoraRelease:
    version: int
    eol: str = ""  # "2027-06-02"; Bodhi leaves it empty for some


@dataclass(frozen=True, slots=True)
class UpgradeProgram:
    name: str
    argv: tuple[str, ...]
    icon: str


def parse_os_release(text: str) -> dict[str, str]:
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            fields[key] = value.strip().strip("\"'")
    return fields


def fedora_version(fields: dict[str, str]) -> int | None:
    """The release number of a regular Fedora; None for anything that does not move between numbered releases."""
    version = fields.get("VERSION_ID", "")
    if fields.get("ID") != "fedora" or not version.isdigit():
        return None
    if fields.get("REDHAT_SUPPORT_PRODUCT_VERSION", "").lower() == "rawhide" or fields.get("VARIANT_ID") == "eln":
        return None
    return int(version)


def running_release() -> int | None:
    for path in OS_RELEASE_PATHS:
        try:
            with open(path, encoding="utf-8") as f:
                return fedora_version(parse_os_release(f.read()))
        except OSError:
            continue
    return None


def parse_releases(payload: object) -> list[FedoraRelease]:
    """Bodhi's /releases/ response -> the Fedora releases that have shipped and are still supported."""
    items = payload.get("releases") if isinstance(payload, dict) else None
    releases = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("id_prefix") != "FEDORA" or item.get("state") != "current":
            continue
        version = str(item.get("version") or "")
        if version.isdigit():
            releases.append(FedoraRelease(int(version), str(item.get("eol") or "")))
    return sorted(releases, key=lambda r: r.version)


def choose_target(running: int, releases: list[FedoraRelease]) -> FedoraRelease | None:
    """The newest shipped release this system can move to directly."""
    reachable = [r for r in releases if running < r.version <= running + MAX_RELEASE_JUMP]
    return max(reachable, key=lambda r: r.version, default=None)


def upgrade_program(desktop: str, which: Callable[[str], str | None] = shutil.which) -> UpgradeProgram | None:
    """The installed program that can upgrade the system, opened on its updates page; the desktop's own one first."""
    programs = [UpgradeProgram("Discover", ("plasma-discover", "--mode", "Update"), "plasmadiscover"),
                UpgradeProgram("GNOME Software", ("gnome-software", "--mode=updates"), "org.gnome.Software")]
    if "gnome" in desktop.lower():
        programs.reverse()
    return next((p for p in programs if which(p.argv[0])), None)
