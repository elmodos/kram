"""A helper request's progress, from the helper's events: the line above the bars, the two bars, the log and the
OpenPGP key question. The front end's dialog shows what `Progress` tells its `ProgressView`."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from ..core.cache import PACKAGEKIT_BLOCKED
from ..i18n import N_, _, ngettext
from .columns import human_size
from .ports import Question, Ui, view_ref

STEP_TEXT = {"install": N_("Installing {nevra}"), "remove": N_("Removing {nevra}"),
             "cleanup": N_("Cleaning up the old copy of {nevra}"),
             "script": N_("Running scriptlet {script} of {nevra}")}
# libdnf5's action names in the helper's "resolved" event
RESOLVED_ACTIONS = {"Install": N_("install"), "Upgrade": N_("upgrade"), "Downgrade": N_("downgrade"),
                    "Reinstall": N_("reinstall"), "Remove": N_("remove"), "Replaced": N_("old copy"),
                    "Reason Change": N_("reason change")}
# what the package bar counts; "Replaced" (the old copy rpm erases after an upgrade, downgrade or reinstall) and
# reason changes are no package of their own
COUNTED = ("Install", "Upgrade", "Downgrade", "Reinstall", "Remove")
# Kram's own messages from the helper, by the key of a "log" event (kram_helper.log) or of a failed "done"
# (kram_helper.fail); unknown keys fall back to the English text. What dnf says is shown as it comes
HELPER_MESSAGES = {
    "no_space": N_("Not enough disk space on {mount}: {size} more is needed"),
    "command": N_("Running: {command}"),
    "loading_repos": N_("Loading repositories…"),
    "refreshing": N_("Refreshing repository metadata…"),
    "mirror_failure": N_("Mirror unavailable: {url}: {error}"),
    "script_error": N_("Scriptlet {script} of {nevra} failed with exit code {code}"),
    "key_imported": N_("Imported key {key_id}"),
    "copying_package": N_("Copying {name}…"),
    "files_removed": N_("Files removed: {count}"),
    "file_removed": N_("Removed {path}"),
    "repo_not_changed": N_("Could not change repository {repo}"),
    "command_failed": N_("Command failed: {command}"),
    "lock_not_installed": N_("Only installed packages can be locked: {names}"),
    "files_not_removed": N_("Files not removed: {count}"),
    "file_changed": N_("{path}: the file changed after it was checked"),
    "file_not_removed": N_("{path}: {error}"),
    "not_root": N_("The helper must run as root"),
}
STAGE_KEYS = ("loading_repos", "refreshing")  # helper messages that also replace the line above the progress bars


WAITING = N_("Waiting for authentication…")
BUSY = N_("Another operation is still running. Try again when it has finished.")


def shows_rpm(request: dict) -> bool:
    """The Installation bar: only requests that run an rpm transaction."""
    return request.get("op") in ("transaction", "local_install")


def shows_download(request: dict) -> bool:
    """The Download bar: everything but a cleanup that only deletes."""
    return not (request.get("op") == "clean_cache" and request.get("target") != "dnf_metadata")


@dataclass(frozen=True)
class Stage:
    """The line above the bars. `kind` "done": `text` in bold, then `detail`; "error": "Error:" in bold, then
    `detail`, all in the error colour."""
    text: str
    kind: Literal["", "done", "error"] = ""
    detail: str = ""


@dataclass(frozen=True)
class Bar:
    """`maximum` 0: busy, without a value."""
    value: int
    maximum: int


BUSY_BAR = Bar(0, 0)


class ProgressView(Protocol):
    def show_stage(self, stage: Stage) -> None: ...

    def show_download(self, bar: Bar, label: str | None) -> None:
        """`label` None: the label stays as it is."""
        ...

    def show_rpm(self, bar: Bar, label: str | None) -> None: ...

    def append_log(self, line: str) -> None: ...

    def request_done(self, ok: bool) -> None:
        """The request is over: the dialog may close now (and closes itself after a success, if the user wants)."""
        ...


class Progress:
    def __init__(self, client, request: dict, view: ProgressView, ui: Ui, now: Callable[[], datetime] = datetime.now):
        """`client`: kram.ipc.client.HelperClient. `ui` asks the key question."""
        self.client, self.request, self._view, self._ui, self._now = client, request, view_ref(view), ui, now
        self.ok = False
        self.result: dict = {}  # the helper's final "done" event
        self.running = True
        self._downloads: dict[int, tuple[float, float]] = {}  # id -> (done, total)
        self._rpm_count = 0
        # from the "resolved" event: rpm counts the erase of a replaced copy as a step of its own, so the bar
        # counts packages instead, and that erase is not shown as a removal
        self._replaced: set[str] = set()
        self._packages = 0
        self._started: set[tuple[str, str]] = set()
        self._last_logged: tuple[str, str] | None = None  # (step, nevra) of the last rpm line in the log
        self._connected = False  # the helper's signals reach this only while it is running the request

    def start(self) -> bool:
        """Send the request. False when the helper is busy with another one: nothing is connected then, since a
        progress left connected to the helper would answer its questions for the rest of the session."""
        if not self.client.request(self.request):
            return False
        self.client.event.connect(self.on_event)
        self.client.failed.connect(self.on_failed)
        self._connected = True
        return True

    def stop(self) -> None:
        if self._connected:
            self._connected = False
            self.client.event.disconnect(self.on_event)
            self.client.failed.disconnect(self.on_failed)

    def _append(self, text: str) -> None:
        self._view.append_log(f"{self._now():%H:%M:%S}  {text}")

    def on_event(self, ev: dict) -> None:
        kind = ev.get("event")
        if kind == "log":
            self._append(helper_text(ev, "text"))
            if ev.get("key") in STAGE_KEYS:  # the password was accepted: say what runs instead
                self._view.show_stage(Stage(helper_text(ev, "text")))
        elif kind == "resolved":
            n = len(ev["items"])
            self._view.show_stage(Stage(ngettext("The transaction has {n} package. Downloading…",
                                                 "The transaction has {n} packages. Downloading…", n).format(n=n)))
            width = max((len(action_text(i["action"])) for i in ev["items"]), default=0)
            for item in ev["items"]:
                self._append(f"{action_text(item['action']):>{width}}  {item['nevra']}")
            self._replaced = {i["nevra"] for i in ev["items"] if i["action"] == "Replaced"}
            self._packages = sum(1 for i in ev["items"] if i["action"] in COUNTED)
        elif kind == "download":
            self._on_download(ev)
        elif kind == "rpm":
            self._on_rpm(ev)
        elif kind == "question":
            self._on_question(ev)
        elif kind == "done":
            self._finish(ev)

    def _on_download(self, ev: dict) -> None:
        i = ev["id"]
        if "name" in ev:
            self._append(_("Downloading {name}").format(name=ev["name"]))
        if ev.get("end"):
            _done, total = self._downloads.get(i, (0, 0))
            self._downloads[i] = (total, total)
            if not ev.get("ok"):
                self._append(_("Download failed: {error}").format(error=ev.get("msg")))
        else:
            self._downloads[i] = (ev.get("done", 0), ev.get("total", 0))
        done = sum(d for d, _t in self._downloads.values())
        total = sum(t for _d, t in self._downloads.values())
        if total > 0:
            # a full bar reads as "finished": the servers that have not said their size yet are not in `total`, and
            # the metadata still has to be read afterwards
            self._view.show_download(Bar(int(1000 * done / total), 0 if done >= total else 1000),
                                     _("Downloaded {done} of {total}").format(done=human_size(int(done)),
                                                                              total=human_size(int(total))))

    def _on_rpm(self, ev: dict) -> None:
        step = ev.get("step")
        self._view.show_download(Bar(1000, 1000), None)
        if step == "prepare":
            self._view.show_stage(Stage(_("Preparing the rpm transaction…")))
        elif step == "element":
            # libdnf5 numbers the transaction elements from 0
            if not self._packages:  # no "resolved" event: rpm's own steps are all there is
                self._rpm_count = ev["count"]
                self._set_rpm_position(ev["index"] + 1)
        elif step in STEP_TEXT:
            if step == "remove" and ev["nevra"] in self._replaced:
                step = "cleanup"
            elif step in ("install", "remove") and self._packages:
                self._started.add((step, ev["nevra"]))
                self._rpm_count = self._packages
                self._set_rpm_position(len(self._started))
            text = _(STEP_TEXT[step]).format(nevra=ev["nevra"], script=ev.get("script", ""))
            self._view.show_stage(Stage(text))
            # "start" and the first "progress" of a package both come with done == 0: log it once
            if step != "script" and ev.get("done") == 0 and self._last_logged != (step, ev["nevra"]):
                self._last_logged = (step, ev["nevra"])
                self._append(text)

    def _set_rpm_position(self, position: int) -> None:
        count = max(self._rpm_count, 1)
        self._view.show_rpm(Bar(min(position, count), count),
                            _("Package {index} of {count}").format(index=min(position, count), count=self._rpm_count))

    def _on_question(self, ev: dict) -> None:
        if ev.get("kind") != "gpg_key":
            self.client.answer(ev["id"], False)
            return
        when = datetime.fromtimestamp(ev["timestamp"]).strftime("%Y-%m-%d") if ev.get("timestamp") else "?"
        text = _("Import the OpenPGP key used to verify packages?\n\n"
                 "User: {user}\nFingerprint: {fingerprint}\nCreated: {created}\nFrom: {url}").format(
            user=", ".join(ev.get("user_ids", [])), fingerprint=ev.get("fingerprint"), created=when, url=ev.get("url"))

        def answered(answer: str | None) -> None:
            yes = answer == "yes"
            self._append((_("Key {key_id}: importing") if yes else _("Key {key_id}: rejected")).format(
                key_id=ev.get("key_id")))
            self.client.answer(ev["id"], yes)
        self._ui.ask(Question(_("Import key"), text), answered)

    def _finish(self, ev: dict) -> None:
        self.running = False
        self.ok = bool(ev.get("ok"))
        self.result = ev
        if self.ok:
            self._view.show_download(Bar(1, 1), None)
            if self._rpm_count:
                self._set_rpm_position(self._rpm_count)
            else:
                self._view.show_rpm(Bar(1, 1), None)
            self._view.show_stage(Stage(_("Done."), "done", _("Packages downloaded.") if ev.get("download_only")
                                        else ""))
            self._append(_("Done."))
        else:
            error = helper_text(ev, "error") or _("unknown error")
            if ev.get("stage") == "locked":
                error = _("Another package operation is running: {process}. Try again when it has finished.").format(
                    process=ev.get("process", "?"))
            elif ev.get("stage") == "packagekit" and ev.get("reason") in PACKAGEKIT_BLOCKED:
                error = _(PACKAGEKIT_BLOCKED[ev["reason"]])
            self._show_error(error, ev.get("details") or [])
        self._view.request_done(self.ok)

    def on_failed(self, message: str) -> None:
        self.running = False
        self._show_error(message, [])
        self._view.request_done(False)

    def _show_error(self, message: str, details: list[str]) -> None:
        self._view.show_download(Bar(0, 1), None)  # stops the busy animation
        self._view.show_stage(Stage(_("Error:"), "error", (message.splitlines() or [_("unknown error")])[0]))
        self._append(_("ERROR: {message}").format(message=message))
        for d in details:
            self._append("  " + d)


def helper_text(ev: dict, field: str) -> str:
    """A helper message translated by its key, else its English `field` ("text" of a log, "error" of a done)."""
    template = HELPER_MESSAGES.get(ev.get("key"))
    if template is None:
        return ev.get(field, "")
    try:
        return _(template).format(**ev.get("params", {}))
    except (KeyError, IndexError):  # a translation with wrong placeholders must not break the log
        return ev.get(field, "")


def action_text(action: str) -> str:
    return _(RESOLVED_ACTIONS[action]) if action in RESOLVED_ACTIONS else action
