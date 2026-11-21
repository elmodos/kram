"""Settings → Watch Fedora Releases: on Reload, ask Fedora's Bodhi service whether a new release is out, and offer
it with a button until the system has reached it. The front end draws the button from `button()` whenever `changed`
is emitted, and when the setting (kram.app.preferences.WATCH_RELEASES) changes."""
from dataclasses import dataclass

from ..core import distro, net
from ..core.mainloop import Post, Signal
from ..core.settings import store as settings
from ..i18n import _
from . import preferences

RELEASE_CHECK_TIMEOUT_S = 15
BUTTON_ICONS = ("fedora-logo-icon", "system-upgrade")


@dataclass(frozen=True)
class ReleaseButton:
    visible: bool
    text: str = "Fedora"
    tooltip: str = ""


class ReleaseWatcher:
    def __init__(self, post: Post):
        self._post = post
        self.running = distro.running_release()
        self.changed = Signal()

    @staticmethod
    def watching() -> bool:
        return preferences.value(preferences.WATCH_RELEASES)

    def target(self) -> int | None:
        """The release the button offers, from the last check. Gone once the system has reached it."""
        target = settings.get("distro/target", 0)
        running = self.running
        if running is None or not self.watching():
            return None
        return target if running < target <= running + distro.MAX_RELEASE_JUMP else None

    def running_eol(self) -> str:
        """The end of life of the running release, from the last check: "" when not known."""
        return settings.get("distro/running_eol", "")

    def button(self) -> ReleaseButton:
        target = self.target()
        if target is None:
            return ReleaseButton(False, tooltip=_("A new Fedora release"))
        return ReleaseButton(True, f"Fedora {target}",
                             _("Fedora {new} is available, you have {old}").format(new=target, old=self.running))

    def check(self) -> None:
        """Ask Bodhi, when watching; the button follows the answer. No network is no news."""
        if self.running is None or not self.watching():
            return
        net.fetch_json(distro.BODHI_RELEASES_URL, timeout_s=RELEASE_CHECK_TIMEOUT_S, post=self._post,
                       done=self._on_reply, failed=lambda _error: None)  # the last result stays

    def _on_reply(self, payload) -> None:
        releases = distro.parse_releases(payload)
        if not releases:  # not the answer we know: the last result stays
            return
        target = distro.choose_target(self.running, releases)
        settings.set("distro/target", target.version if target else 0)
        settings.set("distro/running_eol", next((r.eol for r in releases if r.version == self.running), ""))
        self.changed.emit()
