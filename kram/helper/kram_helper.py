#!/usr/bin/python3 -I
"""Privileged helper for Kram. Runs as root via pkexec.

Deliberately standalone (only the stdlib and libdnf5): pkexec runs it with a clean environment, and this file
is the security boundary, so it should stay small enough to review in one sitting. The GUI imports
`build_goal` from here so its preview resolves exactly the same goal.

Protocol: one JSON request per line on stdin, JSON event lines on stdout.
  {"op": "ping"}
  {"op": "refresh"}                                        re-download metadata of enabled repos
  {"op": "transaction", "install": [...], "remove": [...], "upgrade": [...], "reinstall": [...],
   "downgrade": [...], "mark_user": [...], "mark_dep": [...], "upgrade_all": false,
   "exclude_weak": [...], "download_only": false, "test": false}
                                                           exclude_weak: names never pulled in as recommendations
  {"op": "repo_set_enabled", "repos": {"<repo id>": bool}}  persist via dnf5 config-manager, then load metadata
  {"op": "copr", "action": "enable"|"disable"|"remove", "project": "owner/name", "hub": "<host>"}
  {"op": "answer", "id": N, "yes": bool}                   reply to a "question" event (only while asked)
  {"op": "quit"}
Events: {"event": "log"|"resolved"|"download"|"rpm"|"question"|"done", ...}; every request ends with "done".
"log" events carry an English "text" plus a "key" and "params" so the GUI can show them translated
(pkexec strips the locale from the environment, so the helper does not translate anything itself).
"""
import json
import os
import re
import subprocess
import sys
import time

# Specs are package names or NEVRAs. No '/', so no file paths or URLs can be smuggled in.
SPEC_RE = re.compile(r"^[A-Za-z0-9_.+:~^-]{1,256}$")
MAX_SPECS = 5000
# repo ids as dnf allows them (copr ids contain ':'); additionally checked against the configured repos
REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+-]{0,199}$")
# `dnf5 copr` arguments; must match kram.core.copr
# first characters alphanumeric: an argument starting with "-" would be parsed as an option
COPR_PROJECT_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9_.+-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.+-]{0,99}$")
COPR_HUB_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$")
COPR_DEFAULT_HUB = "copr.fedorainfracloud.org"
COPR_ACTIONS = ("enable", "disable", "remove")
SPEC_FIELDS = ("install", "remove", "upgrade", "reinstall", "downgrade", "mark_user", "mark_dep")

PROGRESS_INTERVAL = 0.1  # s; progress callbacks fire hundreds of times per file, the GUI needs ~10/s

_proto = None  # private copy of the original stdout, see main()


def emit(event: str, **fields) -> None:
    _proto.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")


def log(key: str, template: str, **params) -> None:
    emit("log", key=key, params=params, text=template.format(**params))


class ProtocolError(Exception):
    pass


def specs(req: dict, field: str) -> list[str]:
    value = req.get(field, [])
    if not isinstance(value, list) or len(value) > MAX_SPECS:
        raise ProtocolError(f"{field}: expected a list of at most {MAX_SPECS} specs")
    for s in value:
        if not isinstance(s, str) or not SPEC_RE.match(s):
            raise ProtocolError(f"{field}: invalid package spec {s!r}")
    return value


def validate(req: dict) -> dict[str, list[str]]:
    fields = {f: specs(req, f) for f in SPEC_FIELDS}
    if not (req.get("upgrade_all") or any(fields.values())):
        raise ProtocolError("empty transaction")
    fields["exclude_weak"] = specs(req, "exclude_weak")
    return fields


def build_goal(base, req: dict):
    """Request -> libdnf5 Goal. Shared with the GUI's unprivileged preview.

    `exclude_weak` is added to the base's exclude_from_weak config (`dnf --setopt=exclude_from_weak=`): those
    packages are not installed as recommendations, but still as hard dependencies, and the solver does not swap
    in another alternative of an "(a or b)" recommendation. A long-lived base must restore the option itself."""
    import libdnf5

    fields = validate(req)
    upgrade_all = bool(req.get("upgrade_all"))
    if fields["exclude_weak"]:
        config = base.get_config()
        config.exclude_from_weak = (*config.exclude_from_weak, *fields["exclude_weak"])
    goal = libdnf5.base.Goal(base)
    for s in fields["install"]:
        goal.add_install(s)
    for s in fields["upgrade"]:
        goal.add_upgrade(s)
    for s in fields["reinstall"]:
        goal.add_reinstall(s)
    for s in fields["downgrade"]:
        goal.add_downgrade(s)
    for s in fields["remove"]:
        goal.add_remove(s)
    for s in fields["mark_user"]:
        goal.add_rpm_reason_change(s, libdnf5.transaction.TransactionItemReason_USER)
    for s in fields["mark_dep"]:
        goal.add_rpm_reason_change(s, libdnf5.transaction.TransactionItemReason_DEPENDENCY)
    if upgrade_all:
        goal.add_rpm_upgrade()
    return goal


def make_base(download_cb=None, load=True):
    import libdnf5
    base = libdnf5.base.Base()
    base.load_config()
    base.setup()
    if download_cb is not None:
        base.set_download_callbacks(libdnf5.repo.DownloadCallbacksUniquePtr(download_cb))
    base.get_repo_sack().create_repos_from_system_configuration()
    if load:
        base.get_repo_sack().load_repos()
    return base


def ask(question_id: int, **fields) -> bool:
    """Send a question and block until the GUI answers it. Anything else, or EOF, means no."""
    emit("question", id=question_id, **fields)
    line = sys.stdin.readline()
    try:
        reply = json.loads(line)
    except json.JSONDecodeError:
        return False
    return isinstance(reply, dict) and reply.get("op") == "answer" and reply.get("id") == question_id \
        and reply.get("yes") is True


def refresh() -> None:
    import libdnf5
    download_cb = DownloadProgress()
    base = make_base(download_cb, load=False)
    for repo in libdnf5.repo.RepoQuery(base):
        if repo.is_enabled():
            repo.expire()
    log("refreshing", "Refreshing repository metadata…")
    base.get_repo_sack().load_repos()
    emit("done", ok=True)


def run_command(argv: list[str]) -> bool:
    """Run a dnf5 subcommand (argv only, never a shell); its output goes to the log."""
    log("command", "Running: {command}", command=" ".join(argv))
    proc = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    for line in (proc.stdout + proc.stderr).splitlines():
        if line.strip():
            emit("log", text=line)
    return proc.returncode == 0


def load_metadata() -> None:
    """Load (downloading what is missing) metadata of the enabled repos, e.g. after enabling one."""
    log("loading_repos", "Loading repositories…")
    make_base(DownloadProgress())


def set_repos_enabled(req: dict) -> None:
    repos = req.get("repos")
    if not isinstance(repos, dict) or not 0 < len(repos) <= 500:
        raise ProtocolError("repos: expected a non-empty object of repo id -> bool")
    for repo_id, enabled in repos.items():
        if not REPO_ID_RE.match(repo_id) or not isinstance(enabled, bool):
            raise ProtocolError(f"repos: invalid entry {repo_id!r}")
    import libdnf5
    # keep `base` referenced while iterating: RepoQuery holds weak pointers into it, and a collected Base
    # makes libdnf5 abort on "Dereferencing an invalidated WeakPtr"
    base = make_base(load=False)
    known = {r.get_id() for r in libdnf5.repo.RepoQuery(base)}
    unknown = sorted(set(repos) - known)
    if unknown:
        raise ProtocolError(f"repos: not configured: {', '.join(unknown)}")
    for repo_id, enabled in sorted(repos.items()):
        if not run_command(["dnf5", "-q", "-y", "config-manager", "setopt", f"{repo_id}.enabled={int(enabled)}"]):
            emit("done", ok=False, stage="config", error=f"could not change {repo_id}")
            return
    if any(repos.values()):
        load_metadata()
    emit("done", ok=True)


def copr(req: dict) -> None:
    action, project, hub = req.get("action"), req.get("project"), req.get("hub") or COPR_DEFAULT_HUB
    if action not in COPR_ACTIONS:
        raise ProtocolError(f"copr: unknown action {action!r}")
    if not isinstance(project, str) or not COPR_PROJECT_RE.match(project):
        raise ProtocolError(f"copr: invalid project {project!r}")
    if not isinstance(hub, str) or not COPR_HUB_RE.match(hub):
        raise ProtocolError(f"copr: invalid hub {hub!r}")
    argv = ["dnf5", "-y", "copr"]
    if hub != COPR_DEFAULT_HUB:
        argv.append(f"--hub={hub}")
    if not run_command([*argv, action, project]):
        emit("done", ok=False, stage="copr", error=f"dnf5 copr {action} {project} failed")
        return
    if action == "enable":
        load_metadata()
    emit("done", ok=True)


def run_transaction(req: dict) -> None:
    import libdnf5

    validate(req)  # before the slow repo loading
    test = bool(req.get("test"))
    download_only = bool(req.get("download_only"))

    # Keep Python references: the UniquePtr owns only the C++ side, and if the Python object is collected
    # libdnf5 calls into a dead director and aborts the whole process.
    download_cb, rpm_cb, key_cb = DownloadProgress(), RpmProgress(), KeyImport()
    log("loading_repos", "Loading repositories…")
    base = make_base(download_cb)
    for repo in libdnf5.repo.RepoQuery(base):
        repo.set_callbacks(libdnf5.repo.RepoCallbacksUniquePtr(key_cb.for_repo()))

    tr = build_goal(base, req).resolve()
    if tr.get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
        emit("done", ok=False, stage="resolve", error="\n".join(tr.get_resolve_logs_as_strings()))
        return
    emit("resolved", items=[
        {"action": libdnf5.base.transaction.transaction_item_action_to_string(tp.get_action()),
         "nevra": tp.get_package().get_nevra()}
        for tp in tr.get_transaction_packages()
    ])

    tr.download()
    if download_only:
        emit("done", ok=True, download_only=True)
        return

    tr.set_callbacks(libdnf5.rpm.TransactionCallbacksUniquePtr(rpm_cb))
    tr.set_description("kram")
    result = tr.test() if test else tr.run()
    if result != libdnf5.base.Transaction.TransactionRunResult_SUCCESS:
        problems = list(tr.get_transaction_problems()) + list(tr.get_gpg_signature_problems())
        emit("done", ok=False, stage="run", error=libdnf5.base.Transaction.transaction_result_to_string(result),
             details=problems)
        return
    emit("done", ok=True, test=test)


class _Throttle:
    """Lets a progress event through when enough time has passed, or when it is the first or the last one."""

    def __init__(self):
        self._last: dict = {}

    def __call__(self, key, done, total) -> bool:
        now = time.monotonic()
        last = self._last.get(key)
        if last is not None and done < total and now - last < PROGRESS_INTERVAL:
            return False
        self._last[key] = now
        return True


def _guarded(default):
    """An exception escaping a SWIG director callback calls std::terminate; turn it into a log event instead."""
    def wrap(fn):
        def guarded(*args):
            try:
                result = fn(*args)
            except Exception as e:  # noqa: BLE001
                emit("log", text=f"callback {fn.__name__} failed: {type(e).__name__}: {e}")
                return default
            return default if result is None else result
        guarded.__name__ = fn.__name__
        return guarded
    return wrap


def _callbacks():
    """Callback classes need libdnf5, which is imported lazily so `ping` stays fast."""
    import libdnf5
    OK = libdnf5.repo.DownloadCallbacks.OK

    class DownloadProgress(libdnf5.repo.DownloadCallbacks):
        def __init__(self):
            super().__init__()
            self._next = 0
            self._throttle = _Throttle()

        @_guarded(0)
        def add_new_download(self, user_data, description, total_to_download):
            # the returned int comes back as user_cb_data in progress()/end()
            self._next += 1
            emit("download", id=self._next, name=description, total=total_to_download, done=0)
            return self._next

        @_guarded(OK)
        def progress(self, user_cb_data, total_to_download, downloaded):
            # metadata downloads report total=0 until the size is known; nothing to show yet
            if total_to_download > 0 and self._throttle(user_cb_data, downloaded, total_to_download):
                emit("download", id=user_cb_data, total=total_to_download, done=downloaded)
            return OK

        @_guarded(OK)
        def end(self, user_cb_data, status, msg):
            emit("download", id=user_cb_data, end=True,
                 ok=status != libdnf5.repo.DownloadCallbacks.TransferStatus_ERROR, msg=msg or "")
            return OK

        @_guarded(OK)
        def mirror_failure(self, user_cb_data, msg, url, metadata):
            log("mirror_failure", "Mirror unavailable: {url}: {error}", url=url, error=msg)
            return OK

    class RpmProgress(libdnf5.rpm.TransactionCallbacks):
        def __init__(self):
            super().__init__()
            self._throttle = _Throttle()

        @_guarded(None)
        def transaction_start(self, total):
            emit("rpm", step="prepare", total=total)

        @_guarded(None)
        def install_start(self, item, total):
            emit("rpm", step="install", nevra=item.get_package().get_nevra(), done=0, total=total)

        @_guarded(None)
        def install_progress(self, item, amount, total):
            if self._throttle(item.get_package().get_nevra(), amount, total):
                emit("rpm", step="install", nevra=item.get_package().get_nevra(), done=amount, total=total)

        @_guarded(None)
        def uninstall_start(self, item, total):
            emit("rpm", step="remove", nevra=item.get_package().get_nevra(), done=0, total=total)

        @_guarded(None)
        def uninstall_progress(self, item, amount, total):
            if self._throttle(item.get_package().get_nevra(), amount, total):
                emit("rpm", step="remove", nevra=item.get_package().get_nevra(), done=amount, total=total)

        @_guarded(None)
        def elem_progress(self, item, amount, total):
            emit("rpm", step="element", nevra=item.get_package().get_nevra(), index=amount, count=total)

        @_guarded(None)
        def script_start(self, item, nevra, type):
            emit("rpm", step="script", nevra=libdnf5.rpm.to_full_nevra_string(nevra),
                 script=libdnf5.rpm.TransactionCallbacks.script_type_to_string(type))

        @_guarded(None)
        def script_error(self, item, nevra, type, return_code):
            log("script_error", "Scriptlet {script} of {nevra} failed with exit code {code}",
                script=libdnf5.rpm.TransactionCallbacks.script_type_to_string(type),
                nevra=libdnf5.rpm.to_full_nevra_string(nevra), code=return_code)

    class RepoKeyCallbacks(libdnf5.repo.RepoCallbacks):
        def __init__(self, owner):
            super().__init__()
            self._owner = owner

        @_guarded(False)
        def repokey_import(self, key_info):
            return self._owner.ask(key_info)

        @_guarded(None)
        def repokey_imported(self, key_info):
            log("key_imported", "Imported key {key_id}", key_id=key_info.get_short_key_id())

    class KeyImport:
        """One question per key per transaction, shared by all repos."""

        def __init__(self):
            self._per_repo = []   # keep the director objects alive (see run_transaction)
            self._answers = {}
            self._next_id = 0

        def for_repo(self):
            cb = RepoKeyCallbacks(self)
            self._per_repo.append(cb)
            return cb

        def ask(self, key_info) -> bool:
            fp = key_info.get_fingerprint()
            if fp not in self._answers:
                self._next_id += 1
                self._answers[fp] = ask(self._next_id, kind="gpg_key", key_id=key_info.get_short_key_id(),
                                        fingerprint=fp, user_ids=list(key_info.get_user_ids()),
                                        url=key_info.get_url(), timestamp=key_info.get_timestamp())
            return self._answers[fp]

    return DownloadProgress, RpmProgress, KeyImport


def main() -> int:
    global _proto, DownloadProgress, RpmProgress, KeyImport
    # rpm scriptlets and libdnf5 may write to fd 1; keep a private copy for the protocol and point fd 1 at stderr.
    _proto = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)
    if os.geteuid() != 0 and "--allow-non-root" not in sys.argv:
        emit("done", ok=False, stage="startup", error="helper must run as root")
        return 1
    while line := sys.stdin.readline():
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ProtocolError("request must be an object")
            op = req.get("op")
            if op == "ping":
                emit("done", ok=True, uid=os.geteuid())
            elif op in ("transaction", "refresh", "repo_set_enabled", "copr"):
                if "DownloadProgress" not in globals():
                    DownloadProgress, RpmProgress, KeyImport = _callbacks()
                {"transaction": run_transaction, "refresh": lambda _r: refresh(),
                 "repo_set_enabled": set_repos_enabled, "copr": copr}[op](req)
            elif op == "quit":
                return 0
            else:
                raise ProtocolError(f"unknown op {op!r}")
        except (ProtocolError, json.JSONDecodeError) as e:
            emit("done", ok=False, stage="protocol", error=str(e))
        except Exception as e:  # noqa: BLE001 - libdnf5 raises many types; report, keep serving
            emit("done", ok=False, stage="exception", error=f"{type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
