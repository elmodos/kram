"""Kram's settings file, `~/.config/kram/kram.conf`, read and written without Qt.

The file is in QSettings' INI format: the Qt front end wrote it alone until 0.11, and still keeps the settings only it
can read there (window geometry, splitter and header states: `@ByteArray(…)` blobs). Every other setting goes through
this store, so that both front ends and the tray checker share one file and existing users keep their settings.

Keys are QSettings keys: "search/mode" is the key `mode` in the section `[search]`, a key without a slash lives in
`[General]`. Values are written the way QSettings writes them (`true`/`false`, numbers, escaped and quoted strings),
so QSettings reads them back as it always did, and this store reads what QSettings writes. The escaping and parsing
follow Qt's own `iniEscapedKey`, `iniEscapedString`, `iniUnescapedStringList` and `readIniLine` (qsettings.cpp).

Keys this store does not change are written back byte for byte, whatever they hold: a Qt-only `@ByteArray` key
survives a session of a front end that cannot read it. A write is a read-modify-write of the whole file under Qt's
own lock file (`kram.conf.lock`, the protocol of QLockFile), into a temporary file renamed over the old one. A Qt
front end that writes later notices the changed file and merges only its own changed keys into it
(`tests/test_settings.py` checks that).
"""
import fcntl
import os
import socket
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

LOCK_TIMEOUT_S = 5.0     # a writer holds the lock for milliseconds; past this, write anyway rather than hang the window
STALE_LOCK_S = 30.0      # QLockFile's default stale time


def default_path() -> Path:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "kram" / "kram.conf"


# ---------------------------------------------------------------- QSettings' INI escaping

_KEY_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
_ESCAPES = {"\a": "\\a", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\v": "\\v",
            '"': '\\"', "\\": "\\\\"}
_UNESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", '"': '"', "?": "?",
              "'": "'", "\\": "\\"}
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def escape_key(key: str) -> str:
    """`iniEscapedKey`: a slash becomes a backslash, anything but [A-Za-z0-9_.-] a %XX or %UXXXX escape."""
    out = []
    for ch in key:
        code = ord(ch)
        if ch == "/":
            out.append("\\")
        elif ch in _KEY_SAFE:
            out.append(ch)
        elif code <= 0xFF:
            out.append(f"%{code:02X}")
        else:  # Qt escapes UTF-16 code units: a character beyond the BMP is two of them
            units = ch.encode("utf-16-be")
            out.extend(f"%U{int.from_bytes(units[i:i + 2], 'big'):04X}" for i in range(0, len(units), 2))
    return "".join(out)


def unescape_key(key: str) -> str:
    """`iniUnescapedKey`."""
    out: list[str] = []
    units: list[int] = []  # %U escapes are UTF-16 code units: pairs of them make one character

    def flush_units() -> None:
        if units:
            out.append(b"".join(u.to_bytes(2, "big") for u in units).decode("utf-16-be", "replace"))
            units.clear()

    i, n = 0, len(key)
    while i < n:
        ch = key[i]
        if ch == "\\":
            flush_units()
            out.append("/")
            i += 1
            continue
        if ch != "%" or i == n - 1:
            flush_units()
            out.append(ch)
            i += 1
            continue
        first, digits = i + 1, 2
        if key[i + 1] == "U":
            first, digits = i + 2, 4
        code = key[first:first + digits]
        if len(code) < digits or not all(c in _HEX_DIGITS for c in code):
            flush_units()
            out.append("%")
            i += 1
            continue
        if digits == 4:
            units.append(int(code, 16))
        else:
            flush_units()
            out.append(chr(int(code, 16)))
        i = first + digits
    flush_units()
    return "".join(out)


def escape_string(text: str) -> str:
    """`iniEscapedString`: C-like escapes, UTF-8 as is, quoted when it holds `;` `,` `=` or starts or ends with a
    space. (A comma unquoted would make it a string list to QSettings.)"""
    needs_quotes = False
    escape_next_if_digit = False
    use_codec = not (text.startswith("@ByteArray(") or text.startswith("@Variant("))
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch in ";,=":
            needs_quotes = True
        if escape_next_if_digit and ch in _HEX_DIGITS:
            out.append(f"\\x{code:x}")
            continue
        escape_next_if_digit = False
        if ch == "\0":
            out.append("\\0")
            escape_next_if_digit = True
        elif ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif code <= 0x1F or (code >= 0x7F and not use_codec):
            out.append(f"\\x{code:x}")
            escape_next_if_digit = True
        else:
            out.append(ch)
    result = "".join(out)
    if needs_quotes or result.startswith(" ") or result.endswith(" "):
        result = f'"{result}"'
    return result


def unescape_value(raw: str) -> str | list[str]:
    """`iniUnescapedStringList`: the text of a value, or a list when it has unquoted commas."""
    items: list[str] | None = None
    current: list[str] = []
    in_quotes = quoted = False
    chop_limit = 0
    i, n = 0, len(raw)

    def chop_trailing_spaces() -> None:
        text = "".join(current)
        end = len(text)
        while end > chop_limit and text[end - 1] in " \t":
            end -= 1
        current[:] = [text[:end]]

    def skip_spaces(i: int) -> int:
        while i < n and raw[i] in " \t":
            i += 1
        return i

    def length() -> int:
        return sum(map(len, current))

    i = skip_spaces(0)
    chop_limit = 0
    while i < n:
        ch = raw[i]
        if ch == "\\":
            i += 1
            if i >= n:
                break
            ch = raw[i]
            i += 1
            if ch in _UNESCAPES:
                current.append(_UNESCAPES[ch])
            elif ch == "x":
                value = 0
                start = i
                while i < n and raw[i] in _HEX_DIGITS:
                    value = value * 16 + int(raw[i], 16)
                    i += 1
                if i > start:
                    current.append(chr(value) if value <= 0x10FFFF else "�")
            elif "0" <= ch <= "7":
                value = int(ch)
                while i < n and "0" <= raw[i] <= "7":
                    value = value * 8 + int(raw[i])
                    i += 1
                current.append(chr(value))
            elif ch in "\n\r":
                if i < n and raw[i] in "\n\r" and raw[i] != ch:
                    i += 1
            # any other escaped character is dropped, as Qt does
            chop_limit = length()
        elif ch == '"':
            i += 1
            quoted = True
            in_quotes = not in_quotes
            if not in_quotes:
                i = skip_spaces(i)
                chop_limit = length()
        elif ch == "," and not in_quotes:
            if not quoted:
                chop_trailing_spaces()
            if items is None:
                items = []
            items.append("".join(current))
            current = []
            quoted = False
            i = skip_spaces(i + 1)
            chop_limit = 0
        else:
            j = i + 1
            while j < n and raw[j] not in '\\",':
                j += 1
            current.append(raw[i:j])
            i = j
    if not quoted:
        chop_trailing_spaces()
    text = "".join(current)
    if items is not None:
        items.append(text)
        return items
    return text


def _variant_text(text: str) -> str | None:
    """`stringToVariant` for the cases this store reads: None for a value only Qt can read (@ByteArray, @Variant…)."""
    if text.startswith("@"):
        if text.startswith("@@"):
            return text[1:]
        return None
    return text


def format_value(value: Any) -> str:
    """The text QSettings writes for `value` (after the '=')."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = repr(value)
        return text.removesuffix(".0")
    if isinstance(value, (list, tuple)):
        if not value:
            return "@Invalid()"
        return ", ".join(escape_string(_prefixed(str(v))) for v in value)
    if isinstance(value, str):
        return escape_string(_prefixed(value))
    raise TypeError(f"cannot store a {type(value).__name__} in the settings")


def _prefixed(text: str) -> str:
    # a string starting with "@" would read as one of Qt's typed values: QSettings doubles the "@"
    return "@" + text if text.startswith("@") else text


# ---------------------------------------------------------------- the file

_SPACE = frozenset(" \t\n\r\f\v")
_SPECIAL = frozenset("\n\r\";=\\")


def _lines(data: str) -> Iterator[tuple[str, int]]:
    """`readIniLine`: the logical lines of an INI file without comments, each with the offset of its first '='
    outside quotes (-1: none). A quoted value may span lines; a backslash before a line break continues the line."""
    pos, n = 0, len(data)
    while True:
        start = pos
        while start < n and data[start] in _SPACE:
            start += 1
        i, in_quotes, equals = start, False, -1
        while i < n:
            ch = data[i]
            i += 1
            if ch not in _SPECIAL:
                continue
            if ch == "=":
                if not in_quotes and equals == -1:
                    equals = i - 1
            elif ch in "\n\r":
                if i == start + 1:
                    start += 1
                elif not in_quotes:
                    i -= 1
                    break
            elif ch == "\\":
                if i < n:
                    first = data[i]
                    i += 1
                    if i < n and {first, data[i]} == {"\n", "\r"}:
                        i += 1
            elif ch == '"':
                in_quotes = not in_quotes
            else:  # ";": a comment, to the end of the line
                if i == start + 1:
                    while i < n and data[i] not in "\n\r":
                        i += 1
                    while i < n and data[i] in _SPACE:
                        i += 1
                    start = i
                elif not in_quotes:
                    i -= 1
                    break
        pos = i
        if i <= start:
            return
        yield data[start:i], (equals - start if equals != -1 else -1)


def parse(data: str) -> dict[str, str]:
    """The keys of an INI file in file order, each with its raw value text (what follows the '=')."""
    raw: dict[str, str] = {}
    section = ""
    for line, eq in _lines(data):
        if line.startswith("["):
            end = line.find("]")
            name = (line[1:end] if end != -1 else line[1:]).strip()
            if name.lower() == "general":
                section = ""
            elif name.lower() == "%general":
                section = name[1:] + "/"
            else:
                section = unescape_key(name) + "/"
            continue
        if eq == -1:
            continue
        key = unescape_key(line[:eq].strip())
        raw[section + key] = line[eq + 1:]
    return raw


def serialize(raw: dict[str, str]) -> str:
    """An INI file of `raw`'s keys, grouped into sections in the order the sections first appear."""
    sections: dict[str, list[tuple[str, str]]] = {}
    for key, value in raw.items():
        # "a/b/c": section "a", key "b/c" (written "b\c"), as QSettings does
        section, _sep, name = key.partition("/") if "/" in key else ("", "", key)
        sections.setdefault(section, []).append((name, value))
    blocks = []
    for section, entries in sections.items():
        if not section:
            header = "[General]"
        elif section.lower() == "general":
            header = "[%General]"
        else:
            header = f"[{escape_key(section)}]"
        blocks.append("\n".join([header] + [f"{escape_key(name)}={value}" for name, value in entries]) + "\n")
    return "\n".join(blocks)


# ---------------------------------------------------------------- QLockFile's protocol

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_if_stale(lock: Path) -> bool:
    """A lock file left behind by a writer that is gone: removed, True. QLockFile holds an flock on the file while it
    holds the lock, so a lock nobody holds an flock on, written by a dead process or long ago, is stale."""
    try:
        fd = os.open(lock, os.O_RDWR)
    except OSError:
        return True  # gone meanwhile: try again
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False  # somebody holds it
        try:
            pid = int(os.pread(fd, 64, 0).split(b"\n", 1)[0])
        except ValueError:
            pid = 0
        age = time.time() - os.fstat(fd).st_mtime
        if pid and _pid_alive(pid) and age < STALE_LOCK_S:
            return False  # it is between creating the file and locking it
        try:
            os.unlink(lock)
        except FileNotFoundError:
            pass
        return True
    finally:
        os.close(fd)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock = path.with_name(path.name + ".lock")
    fd = None
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            if _remove_if_stale(lock):
                continue
            if time.monotonic() > deadline:
                break
            time.sleep(0.01)
            continue
        except OSError:
            break  # a read-only directory, say: the write itself reports it
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            pass
        os.write(fd, f"{os.getpid()}\nkram\n{socket.gethostname()}\n".encode())
        break
    try:
        yield
    finally:
        if fd is not None:
            try:
                os.unlink(lock)
            except FileNotFoundError:
                pass
            os.close(fd)


# ---------------------------------------------------------------- the store

class Settings:
    """The settings file at `path` (None: `default_path()`, looked up at every access, so a test's XDG_CONFIG_HOME
    applies). Reads come from a copy that is read again whenever the file changed; every write goes to the file at
    once."""

    def __init__(self, path: str | os.PathLike | None = None):
        self._path = Path(path) if path is not None else None
        self._cache: tuple[tuple, Path, dict[str, str]] | None = None

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else default_path()

    def _read(self, path: Path) -> dict[str, str]:
        try:
            st = path.stat()
        except OSError:
            return {}
        stamp = (st.st_ino, st.st_size, st.st_mtime_ns)
        cache = self._cache
        if cache is not None and cache[0] == stamp and cache[1] == path:
            return cache[2]
        try:
            raw = parse(path.read_bytes().decode("utf-8", "replace"))
        except OSError:
            return {}
        self._cache = (stamp, path, raw)
        return raw

    def _write(self, change) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with _locked(path):
            self._cache = None
            raw = dict(self._read(path))
            if not change(raw):
                return
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
                    out.write(serialize(raw))
                try:
                    os.chmod(tmp, path.stat().st_mode & 0o7777)
                except FileNotFoundError:
                    os.chmod(tmp, 0o644)
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            self._cache = None

    def contains(self, key: str) -> bool:
        return key in self._read(self.path)

    def get(self, key: str, default: Any = None, type: type | None = None) -> Any:  # noqa: A002 - QSettings' name
        """The value of `key` as `type` (by default the type of `default`; a string when both are None), `default`
        when it is not set or cannot be read as that type. A value only Qt can read counts as not set."""
        raw = self._read(self.path).get(key)
        if raw is None:
            return default
        value = unescape_value(raw)
        if isinstance(value, list):
            items = [_variant_text(v) for v in value]
            if any(v is None for v in items):
                return default
            text = ", ".join(items)  # type: ignore[arg-type]
        else:
            text = _variant_text(value)
            if text is None:
                return default
        if type is None and default is not None:
            type = default.__class__
        if type is list:
            return [_variant_text(v) for v in value] if isinstance(value, list) else [text]
        if type is bool:
            return text.strip().lower() not in ("", "0", "false")
        if type is int:
            try:
                return int(text.strip())
            except ValueError:
                return default
        if type is float:
            try:
                return float(text.strip())
            except ValueError:
                return default
        return text

    def set(self, key: str, value: Any) -> None:
        text = format_value(value)

        def change(raw: dict[str, str]) -> bool:
            if raw.get(key) == text:
                return False
            raw[key] = text
            return True
        self._write(change)

    def remove(self, key: str) -> None:
        def change(raw: dict[str, str]) -> bool:
            return raw.pop(key, None) is not None
        self._write(change)

    def sync(self) -> None:
        """Forget the copy: the next read reads the file. (Writes need no sync: they are in the file already.)"""
        self._cache = None


store = Settings()  # the user's kram.conf
