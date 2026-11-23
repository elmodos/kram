"""Asking a web service without a toolkit: `fetch` and `fetch_json` run the request on a thread of its own and hand the
answer to the main loop through `post` (kram.core.mainloop's contract: the front end's `post` runs a call on its
main thread).

Kram asks three services: Fedora's Bodhi for the releases (Watch Fedora Releases), and Copr for a project search and
for each enabled project's builds (the Fedora N dialog). None of them may hold the dnf thread, so the requests have
threads of their own: daemon threads, so a slow answer never keeps Kram from quitting.

Every failure, whatever it was (no network, a timeout, an HTTP error, an answer that is not JSON), is one exception,
`NetError`, whose text the dialogs show as it is.
"""
import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from .. import __version__

# Say what we are. urllib's default "Python-urllib/3.x" is no better than a browser's: Bodhi answers clients it does
# not know with an HTML bot check instead of JSON (it did so to Qt's "Mozilla/5.0").
USER_AGENT = f"Kram/{__version__}"


class NetError(Exception):
    """A request that brought no usable answer. `str()` is the reason, for the user."""


class Request:
    """A request on its way. After `cancel` neither `done` nor `failed` is called: a search that a newer one
    replaced, or one for a dialog that was closed, is dropped on the main thread, whenever its thread finishes."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


def url_with(url: str, params: Mapping[str, str] | None) -> str:
    """`url` with `params` as its query, escaped."""
    return f"{url}?{urllib.parse.urlencode(params)}" if params else url


def as_net_error(e: Exception) -> NetError:
    """The one `NetError` for whatever a request raised: `str()` of it is the reason for the user."""
    if isinstance(e, urllib.error.HTTPError):
        return NetError(f"HTTP {e.code}: {e.reason}")
    if isinstance(e, urllib.error.URLError):
        reason = e.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return NetError("Operation timed out")
        return NetError(str(getattr(reason, "strerror", None) or reason))
    if isinstance(e, (TimeoutError, socket.timeout)):  # a timeout while reading the body
        return NetError("Operation timed out")
    if isinstance(e, OSError):
        return NetError(e.strerror or str(e))
    return NetError(str(e))


def open_url(url: str, timeout_s: float, headers: Mapping[str, str] | None = None):
    """The open response of a GET (a context manager), or a `NetError`."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        return urllib.request.urlopen(request, timeout=timeout_s)  # noqa: S310 (http(s) URLs only: callers check)
    except OSError as e:
        raise as_net_error(e) from e


def _read(url: str, timeout_s: float, headers: Mapping[str, str]) -> bytes:
    try:
        with open_url(url, timeout_s, headers) as answer:
            return answer.read()
    except NetError:
        raise
    except OSError as e:  # a failure while reading the body
        raise as_net_error(e) from e


def fetch(url: str, *, timeout_s: float, post: Callable[[Callable[[], None]], None],
          done: Callable[[bytes], None], failed: Callable[[NetError], None],
          params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None,
          parse: Callable[[bytes], Any] | None = None) -> Request:
    """GET `url` (with `params` as its query) and call `done(body)` or `failed(error)` on the main thread. `parse`,
    when given, turns the body into the result on the request's thread; a `ValueError` from it is a failure."""
    request = Request()
    full_url = url_with(url, params)

    def run() -> None:
        try:
            body = _read(full_url, timeout_s, headers or {})
            result = parse(body) if parse is not None else body
        except NetError as e:
            outcome = (failed, e)
        except ValueError as e:
            outcome = (failed, NetError(str(e) or "Unexpected answer"))
        else:
            outcome = (done, result)

        def deliver() -> None:
            if not request.cancelled:
                outcome[0](outcome[1])
        if not request.cancelled:
            post(deliver)

    threading.Thread(target=run, name="kram-net", daemon=True).start()
    return request


def fetch_json(url: str, *, timeout_s: float, post: Callable[[Callable[[], None]], None],
               done: Callable[[Any], None], failed: Callable[[NetError], None],
               params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None) -> Request:
    """`fetch`, asking for JSON and handing over the decoded answer. An answer that is not JSON is a `NetError`."""
    return fetch(url, timeout_s=timeout_s, post=post, done=done, failed=failed, params=params,
                 headers={"Accept": "application/json", **(headers or {})}, parse=_json)


def _json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError("The answer is not JSON") from e
