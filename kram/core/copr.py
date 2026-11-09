"""COPR helpers: repo ids <-> project specs, and Copr API search results. No Qt, no libdnf5."""
import re
from dataclasses import dataclass

DEFAULT_HUB = "copr.fedorainfracloud.org"
SEARCH_URL = "https://{hub}/api_3/project/search"
PROJECT_URL = "https://{hub}/api_3/project"
# owner/project, or @group/project; what `dnf5 copr enable` accepts
# first characters alphanumeric: an argument starting with "-" would be parsed as an option
PROJECT_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9_.+-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.+-]{0,99}$")
HUB_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$")


@dataclass(frozen=True, slots=True)
class CoprRef:
    hub: str
    project: str   # "owner/name" or "@group/name"


def parse_repo_id(repo_id: str) -> CoprRef | None:
    """'copr:copr.fedorainfracloud.org:group_kde:plasma' -> CoprRef(hub, '@kde/plasma')."""
    parts = repo_id.split(":")
    if len(parts) != 4 or parts[0] != "copr":
        return None
    _copr, hub, owner, name = parts
    if owner.startswith("group_"):
        owner = "@" + owner.removeprefix("group_")
    project = f"{owner}/{name}"
    if not (HUB_RE.match(hub) and PROJECT_RE.match(project)):
        return None
    return CoprRef(hub, project)


@dataclass(frozen=True, slots=True)
class CoprProject:
    full_name: str
    description: str
    homepage: str
    chroots: tuple[str, ...]

    def has_chroot(self, releasever: str, basearch: str) -> bool:
        return f"fedora-{releasever}-{basearch}" in self.chroots


def parse_chroots(payload: object) -> set[str]:
    """Copr API v3 /project response -> the chroots it builds for, e.g. "fedora-45-x86_64"."""
    repos = payload.get("chroot_repos") if isinstance(payload, dict) else None
    if not isinstance(repos, dict):
        raise ValueError("no chroot_repos in the response")
    return set(repos)


def parse_search(payload: dict) -> list[CoprProject]:
    """Copr API v3 /project/search response -> projects."""
    projects = []
    for item in payload.get("items", []):
        name = item.get("full_name") or ""
        if not PROJECT_RE.match(name):
            continue
        projects.append(CoprProject(
            full_name=name,
            description=" ".join((item.get("description") or "").split()),
            homepage=item.get("homepage") or "",
            chroots=tuple(sorted((item.get("chroot_repos") or {}).keys())),
        ))
    return projects


def rank(projects: list[CoprProject], text: str) -> list[CoprProject]:
    """Copr returns matches in project-id order; put the ones whose name matches the query first."""
    q = text.strip().lower()

    def key(p: CoprProject):
        full = p.full_name.lower()
        name = full.split("/", 1)[1]
        if full == q:
            tier = 0
        elif name == q:
            tier = 1
        elif name.startswith(q):
            tier = 2
        elif q in name:
            tier = 3
        elif q in full:
            tier = 4
        else:
            tier = 5  # matched on description only
        return tier, len(name), full

    return sorted(projects, key=key)
