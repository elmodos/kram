"""Release notes for "What's New": the <releases> of the AppStream metainfo, the same text software centres show.
English only, by choice."""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .. import APP_ID

# a source checkout first, then where the package installs it
METAINFO = (Path(__file__).resolve().parents[2] / "data" / f"{APP_ID}.metainfo.xml",
            Path("/usr/share/metainfo") / f"{APP_ID}.metainfo.xml")


@dataclass(slots=True)
class Release:
    version: str
    date: str
    paragraphs: list[str]
    items: list[str]


def _text(element) -> str:
    return " ".join("".join(element.itertext()).split())


def load(paths: tuple[Path, ...] = METAINFO) -> list[Release]:
    """Newest first, as the metainfo lists them; [] if no metainfo is found."""
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        releases = []
        for r in root.iterfind("releases/release"):
            description = r.find("description")
            paragraphs = [_text(p) for p in description.iterfind("p")] if description is not None else []
            items = [_text(li) for li in description.iterfind("ul/li")] if description is not None else []
            releases.append(Release(r.get("version", ""), r.get("date", ""), paragraphs, items))
        return releases
    return []
