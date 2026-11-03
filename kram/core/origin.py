import re

from .model import Origin

# TODO: move to user config once there is a settings file.
OFFICIAL_REPOS = frozenset({
    "fedora", "updates", "updates-testing", "fedora-cisco-openh264", "anaconda",
})

# Packages installed from the installation media carry a hex hash as their from_repo_id.
_INSTALLER_REPO = re.compile(r"^[0-9a-f]{32}$")


def classify(repo_id: str, official: frozenset[str] = OFFICIAL_REPOS) -> Origin:
    if repo_id in official or _INSTALLER_REPO.match(repo_id):
        return Origin.FEDORA
    if repo_id.startswith("copr:"):
        return Origin.COPR
    if repo_id == "@commandline":
        return Origin.LOCAL
    if not repo_id or repo_id in ("<unknown>", "@System"):
        return Origin.UNKNOWN
    return Origin.THIRD_PARTY


def display_repo(repo_id: str) -> str:
    """copr:copr.fedorainfracloud.org:owner:project -> owner/project"""
    if repo_id.startswith("copr:"):
        parts = repo_id.split(":")
        if len(parts) >= 4:
            return "/".join(parts[2:])
    return repo_id
