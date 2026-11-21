"""Comps group icons from the system icon theme; which names to look for is kram.app.icons.group_icon_names."""
from functools import cache

from PySide6.QtGui import QIcon

from ..app.icons import group_icon_names


def _themed(names: tuple[str, ...]) -> QIcon:
    for name in names:
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name)
    return QIcon()


@cache
def group_icon(group_id: str) -> QIcon:
    """The themed icon for a comps group id or an environment's GroupInfo.key; "" is the "All groups" entry."""
    names, fallback = group_icon_names(group_id)
    icon = _themed(names)
    return _themed(fallback) if icon.isNull() and fallback else icon
