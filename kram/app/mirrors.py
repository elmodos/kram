"""Repositories → Mirrors…: the mirrors of one repository, a speed test of them, and choosing one (or going back to
letting libdnf5 choose). The front end draws what `Mirrors` tells its `MirrorsView`. A choice goes to `on_choice` as a
`MirrorChoice`, and the main window runs it through the helper (kram.core.mirrors says how a choice is applied) while
the dialog stays open; after the reload `update` shows the new state."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ..core import mirrors as core
from ..core.mainloop import Post
from ..core.mirrors import Mirror, MirrorSource, Probe, SpeedTest
from ..core.net import NetError
from ..i18n import _, ngettext
from .columns import human_size
from .ports import CANCEL, Button, Question, Ui, view_ref
from .repos import ActionState


@dataclass(frozen=True)
class MirrorChoice:
    """What the user decided. `repo` "" leaves the repository as it is; else `baseurl` is the mirror it is pinned to,
    None to let libdnf5 choose again. `fastestmirror` None leaves dnf's option as it is."""
    repo: str = ""
    baseurl: str | None = None
    fastestmirror: bool | None = None


@dataclass(frozen=True)
class MirrorLine:
    mirror: Mirror
    name: str       # the address without the scheme and the closing "/"
    country: str
    protocol: str
    response: str   # time to answer: "85 ms", "—" before it is known
    speed: str      # "12.3 MB/s"; "—" when it was not measured
    note: str       # "In use", "Fastest", "Out of date", or why it failed
    current: bool
    failed: bool


@dataclass(frozen=True)
class MirrorButtons:
    test: bool
    use: ActionState
    automatic: ActionState


class MirrorsView(Protocol):
    def show_lines(self, lines: list[MirrorLine]) -> None:
        """Draw these rows. The view keeps the selection, by the mirror's address."""
        ...

    def show_status(self, text: str) -> None: ...

    def set_testing(self, on: bool) -> None:
        """A test runs: the Test button says Stop."""
        ...

    def show_fastest(self, text: str, button: str) -> None:
        """What dnf's fastestmirror option is now, and the label of the button that switches it."""
        ...


def speed_text(bps: float | None) -> str:
    return f"{human_size(int(bps))}/s" if bps else "—"


def response_text(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds * 1000:.0f} ms" if seconds < 10 else f"{seconds:.0f} s"


def dialog_title(repo) -> str:
    """The dialog's title for `repo` (a `RepoInfo`)."""
    return _("Mirrors of {repo}").format(repo=repo.name or repo.id)


def short_name(url: str) -> str:
    parts = urlsplit(url)
    return (parts.netloc + parts.path).rstrip("/")


class Mirrors:
    def __init__(self, repo_id: str, source: MirrorSource, fastestmirror: bool, view: MirrorsView, ui: Ui, post: Post,
                 *, on_choice: Callable[[MirrorChoice], None] | None = None,
                 fetch: Callable[..., object] = core.fetch_mirrors,
                 speed_test: Callable[..., SpeedTest] = SpeedTest):
        """`on_choice(choice)` applies a choice while the dialog stays open. `fetch` and `speed_test` are the
        network, replaced in the tests."""
        self.repo_id, self.source, self.fastestmirror = repo_id, source, fastestmirror
        self._view, self._ui, self._post = view_ref(view), ui, post
        self._on_choice = on_choice
        self._speed_test_factory = speed_test
        self.choice: MirrorChoice | None = None
        self.mirrors: list[Mirror] = []
        self.probes: dict[str, Probe] = {}
        self._test: SpeedTest | None = None
        self._finished = False   # a test ran to its end: the rows are ordered by speed
        self._closed = False
        self._status = _("Loading the list of mirrors…")
        self._request = fetch(source, post=post, done=self._loaded, failed=self._load_failed)

    def start(self) -> None:
        """Draw the first state; once the view exists (it is built after this object)."""
        self._view.show_status(self._status)
        self._view.set_testing(False)
        self._view.show_fastest(self.fastest_text(), self.fastest_button_text())

    def update(self, source: MirrorSource, fastestmirror: bool) -> None:
        """The state after a choice was applied (or failed: the reload says what is configured now). The list and what
        the test found stay."""
        before = self.choice
        self.source, self.fastestmirror = source, fastestmirror
        self.mirrors = self._with_pinned(self.mirrors) if self.mirrors else self.mirrors
        self._view.show_fastest(self.fastest_text(), self.fastest_button_text())
        if before is not None and before.repo:
            if source.pinned and before.baseurl and source.pinned.rstrip("/") == before.baseurl.rstrip("/"):
                self._say(_("The repository now downloads from {mirror}.").format(mirror=short_name(source.pinned)))
            elif not source.pinned and before.baseurl is None:
                self._say(_("The repository takes its mirrors from the list again."))
        self.choice = None
        self._draw()

    def _with_pinned(self, mirrors: list[Mirror]) -> list[Mirror]:
        pinned = self.source.pinned
        if pinned and not any(m.url.rstrip("/") == pinned.rstrip("/") for m in mirrors):
            # chosen from a list that has since changed, or by hand: it is still what the repository uses
            return [*mirrors, Mirror(pinned.rstrip("/") + "/", urlsplit(pinned).scheme)]
        return mirrors

    def close(self) -> None:
        self._closed = True  # answers that arrive later are for a dialog that is gone
        self._request.cancel()
        if self._test is not None:
            self._test.cancel()

    # ---------------------------------------------------------------- the list

    def _loaded(self, mirrors: list[Mirror]) -> None:
        if self._closed:
            return
        mirrors = self._with_pinned(mirrors)
        self.mirrors = mirrors
        if not mirrors:
            self._say(_("The list has no mirrors."))
            return
        self._say(ngettext("{n} mirror. Test the speed to see which is the quickest.",
                           "{n} mirrors. Test the speed to see which is the quickest.", len(mirrors)).format(
                               n=len(mirrors)))
        self._draw()

    def _load_failed(self, error: NetError) -> None:
        if not self._closed:
            self._say(_("Could not get the list of mirrors: {error}").format(error=error))

    def _say(self, text: str) -> None:
        self._status = text
        self._view.show_status(text)

    def _is_current(self, mirror: Mirror) -> bool:
        return bool(self.source.pinned) and mirror.url.rstrip("/") == self.source.pinned.rstrip("/")

    def _newest_revision(self) -> int:
        return max((p.revision for p in self.probes.values() if p.revision is not None), default=0)

    def _stale(self, url: str) -> bool:
        revision, newest = self.probes.get(url, Probe()).revision, self._newest_revision()
        return revision is not None and bool(newest) and revision < newest

    def lines(self) -> list[MirrorLine]:
        # a mirror with older metadata is never "the fastest": it would be quick because it has less to offer
        ranked = [m for m in self.mirrors if self.probes.get(m.url, Probe()).speed_bps and not self._stale(m.url)]
        fastest = max(ranked, key=lambda m: self.probes[m.url].speed_bps).url if ranked and self._finished else None
        lines = []
        for m in self.mirrors:
            p = self.probes.get(m.url, Probe())
            if p.error:
                note = p.error
            elif self._stale(m.url):
                note = _("Out of date")
            elif m.url == fastest:
                note = _("Fastest")
            else:
                note = ""
            if self._is_current(m):
                note = f"{_('In use')}. {note}" if note else _("In use")
            lines.append(MirrorLine(m, short_name(m.url), m.country, m.protocol.upper(), response_text(p.latency_s),
                                    speed_text(p.speed_bps), note, self._is_current(m), bool(p.error)))
        if self._finished:  # not before: rows that move under the cursor while the test runs are hard to follow
            lines.sort(key=lambda ln: self._order(ln))
        return lines

    def _order(self, line: MirrorLine) -> tuple:
        p = self.probes.get(line.mirror.url, Probe())
        return (line.failed, self._stale(line.mirror.url), -(p.speed_bps or 0),
                p.latency_s if p.latency_s is not None else 1e9)

    def _draw(self) -> None:
        self._view.show_lines(self.lines())

    # ---------------------------------------------------------------- the test

    @property
    def testing(self) -> bool:
        return self._test is not None

    def toggle_test(self) -> None:
        self.stop_test() if self.testing else self.test()

    def test(self) -> None:
        if self.testing or not self.mirrors:
            return
        self.probes, self._finished = {}, False
        self._test = self._speed_test_factory(self.mirrors, self._post, self._probed, self._test_done)
        self._view.set_testing(True)
        self._say(_("Testing the mirrors…"))
        self._draw()
        self._test.start()

    def stop_test(self) -> None:
        if self._test is not None:
            self._test.cancel()
            self._test = None
        self._view.set_testing(False)
        self._say(_("The test was stopped."))
        self._draw()

    def _probed(self, mirror: Mirror, probe: Probe) -> None:
        if self._closed or self._test is None:
            return
        self.probes[mirror.url] = probe
        done = sum(1 for p in self.probes.values() if p.latency_s is not None or p.error)
        self._say(_("Testing the mirrors… {done} of {n} answered").format(done=done, n=len(self.mirrors)))
        self._draw()

    def _test_done(self) -> None:
        if self._closed or self._test is None:
            return
        self._test, self._finished = None, True
        self._view.set_testing(False)
        ok = [p for p in self.probes.values() if not p.error]
        if len(ok) < len(self.mirrors):
            self._say(_("{n} of {total} mirrors answered. The quickest is first.").format(n=len(ok),
                                                                                         total=len(self.mirrors)))
        else:
            self._say(_("The test is done. The quickest mirror is first."))
        self._draw()

    # ---------------------------------------------------------------- choosing

    def mirror_by_url(self, url: str | None) -> Mirror | None:
        return next((m for m in self.mirrors if m.url == url), None)

    def buttons(self, url: str | None) -> MirrorButtons:
        """For the selected row (its address) and the state of the dialog."""
        return MirrorButtons(bool(self.mirrors), self._use_state(url), self._automatic_state())

    def _use_state(self, url: str | None) -> ActionState:
        mirror = self.mirror_by_url(url)
        if mirror is None:
            return ActionState(False, _("Select a mirror."))
        probe = self.probes.get(mirror.url)
        if probe is not None and probe.error:
            return ActionState(False, _("This mirror did not answer the test."))
        if self._is_current(mirror):
            return ActionState(False, _("The repository already uses this mirror."))
        return ActionState(True, "")

    def _automatic_state(self) -> ActionState:
        if self.source.pinned:
            return ActionState(True, "")
        return ActionState(False, _("The repository takes its mirrors from the list already."))

    def use(self, url: str | None) -> None:
        """Pin the repository to the mirror at `url`."""
        mirror = self.mirror_by_url(url)
        if mirror is None or not self._use_state(url).enabled:
            return
        reasons = []
        if self._stale(mirror.url):
            reasons.append(_("Its copy of the repository is older than another mirror's, so it may be missing "
                             "updates."))
        if mirror.protocol != "https":
            reasons.append(_("It is not reached over https."))
        if not reasons:
            self._choose(mirror)
            return
        buttons = (Button("use", _("Use This Mirror"), "accept"), CANCEL)

        def answered(answer: str | None) -> None:
            if answer == "use":
                self._choose(mirror)
        self._ui.ask(Question(_("Use this mirror?"), short_name(mirror.url), buttons, informative="\n\n".join(reasons),
                              icon="warning"), answered)

    def _apply(self, choice: MirrorChoice) -> None:
        """Hand the choice over; the dialog stays open, and `update` follows once it is applied."""
        self.choice = choice
        if self._on_choice is not None:
            self._on_choice(choice)

    def _choose(self, mirror: Mirror) -> None:
        self._apply(MirrorChoice(self.repo_id, mirror.url))

    def use_automatic(self) -> None:
        if self._automatic_state().enabled:
            self._apply(MirrorChoice(self.repo_id, None))

    # ---------------------------------------------------------------- dnf's own option

    def fastest_text(self) -> str:
        return (_("dnf tests the mirrors of a list itself and uses the fastest, for every repository.")
                if self.fastestmirror else
                _("dnf uses the first mirrors of a list that answer, for every repository."))

    def fastest_button_text(self) -> str:
        return _("Turn Off Fastest Mirror Search") if self.fastestmirror else _("Turn On Fastest Mirror Search")

    def toggle_fastest(self) -> None:
        self._apply(MirrorChoice(fastestmirror=not self.fastestmirror))
