#!/usr/bin/python3 -I
"""Privileged helper for Kram. Runs as root via pkexec.

Deliberately standalone (no kram imports): pkexec runs it with a clean environment, and this file is the
security boundary, so it should stay small enough to review in one sitting.

Protocol: one JSON request per line on stdin, JSON event lines on stdout.
  {"op": "ping"}
  {"op": "transaction", "install": [...], "remove": [...], "upgrade": [...], "upgrade_all": false, "test": false}
  {"op": "quit"}
Events: {"event": "log"|"resolved"|"download"|"rpm"|"done", ...}
"""
import json
import os
import re
import sys

# Specs are package names or NEVRAs. No '/', so no file paths or URLs can be smuggled in.
SPEC_RE = re.compile(r"^[A-Za-z0-9_.+:~^-]{1,256}$")
MAX_SPECS = 5000

# rpm scriptlets and libdnf5 may write to fd 1; keep a private copy for the protocol and point fd 1 at stderr.
_proto = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
os.dup2(2, 1)


def emit(event: str, **fields) -> None:
    _proto.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")


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


def make_base():
    import libdnf5
    base = libdnf5.base.Base()
    base.load_config()
    base.setup()
    repo_sack = base.get_repo_sack()
    repo_sack.create_repos_from_system_configuration()
    repo_sack.load_repos()
    return base


def run_transaction(req: dict) -> None:
    import libdnf5

    install, remove, upgrade = specs(req, "install"), specs(req, "remove"), specs(req, "upgrade")
    upgrade_all = bool(req.get("upgrade_all"))
    test = bool(req.get("test"))
    if not (install or remove or upgrade or upgrade_all):
        raise ProtocolError("empty transaction")

    emit("log", text="Завантаження репозиторіїв…")
    base = make_base()
    goal = libdnf5.base.Goal(base)
    for s in install:
        goal.add_install(s)
    for s in remove:
        goal.add_remove(s)
    for s in upgrade:
        goal.add_upgrade(s)
    if upgrade_all:
        goal.add_rpm_upgrade()

    tr = goal.resolve()
    if tr.get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
        emit("done", ok=False, stage="resolve", error="\n".join(tr.get_resolve_logs_as_strings()))
        return
    emit("resolved", items=[
        {"action": libdnf5.base.transaction.transaction_item_action_to_string(tp.get_action()),
         "nevra": tp.get_package().get_nevra()}
        for tp in tr.get_transaction_packages()
    ])

    # Keep Python references: the UniquePtr owns only the C++ side, and if the Python object is collected
    # libdnf5 calls into a dead director and aborts the whole process.
    download_cb, rpm_cb = DownloadProgress(), RpmProgress()
    base.set_download_callbacks(libdnf5.repo.DownloadCallbacksUniquePtr(download_cb))
    tr.download()

    tr.set_callbacks(libdnf5.rpm.TransactionCallbacksUniquePtr(rpm_cb))
    tr.set_description("kram")
    if test:
        result = tr.test()
    else:
        result = tr.run()
    if result != libdnf5.base.Transaction.TransactionRunResult_SUCCESS:
        problems = list(tr.get_transaction_problems()) + list(tr.get_gpg_signature_problems())
        emit("done", ok=False, stage="run", error=libdnf5.base.Transaction.transaction_result_to_string(result),
             details=problems)
        return
    emit("done", ok=True, test=test)


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
            self._names = {}
            self._next = 0

        @_guarded(0)
        def add_new_download(self, user_data, description, total_to_download):
            # the returned int comes back as user_cb_data in progress()/end()
            self._next += 1
            self._names[self._next] = description
            emit("download", id=self._next, name=description, total=total_to_download, done=0)
            return self._next

        @_guarded(OK)
        def progress(self, user_cb_data, total_to_download, downloaded):
            emit("download", id=user_cb_data, total=total_to_download, done=downloaded)
            return OK

        @_guarded(OK)
        def end(self, user_cb_data, status, msg):
            emit("download", id=user_cb_data, end=True, ok=status != libdnf5.repo.DownloadCallbacks.TransferStatus_ERROR,
                 msg=msg or "")
            return OK

        @_guarded(OK)
        def mirror_failure(self, user_cb_data, msg, url, metadata):
            emit("log", text=f"Дзеркало недоступне: {url}: {msg}")
            return OK

    class RpmProgress(libdnf5.rpm.TransactionCallbacks):
        @_guarded(None)
        def transaction_start(self, total):
            emit("rpm", step="prepare", total=total)

        @_guarded(None)
        def install_start(self, item, total):
            emit("rpm", step="install", nevra=item.get_package().get_nevra(), done=0, total=total)

        @_guarded(None)
        def install_progress(self, item, amount, total):
            emit("rpm", step="install", nevra=item.get_package().get_nevra(), done=amount, total=total)

        @_guarded(None)
        def uninstall_start(self, item, total):
            emit("rpm", step="remove", nevra=item.get_package().get_nevra(), done=0, total=total)

        @_guarded(None)
        def uninstall_progress(self, item, amount, total):
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
            emit("log", text=f"Скрипт {libdnf5.rpm.TransactionCallbacks.script_type_to_string(type)} "
                             f"{libdnf5.rpm.to_full_nevra_string(nevra)} завершився з кодом {return_code}")

    return DownloadProgress, RpmProgress


def main() -> int:
    if os.geteuid() != 0 and "--allow-non-root" not in sys.argv:
        emit("done", ok=False, stage="startup", error="helper must run as root")
        return 1
    global DownloadProgress, RpmProgress
    for line in sys.stdin:
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
            elif op == "transaction":
                if "DownloadProgress" not in globals():
                    DownloadProgress, RpmProgress = _callbacks()
                run_transaction(req)
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
