# A GTK front end for Kram — implementation plan

Status: **phase 2 under way** (2026-11-22) on branch `feature/gtk`: spikes S1–S9 done (§14); `kram/gtk` has the
main window and every dialog over `kram/app` (§7.4 steps 2–6); polish, translations and packaging are next (§16). **Phase 1 done** (2026-11-21): the logic extraction (P1.0–P1.15) and the rename to `kram/qt` (P1.16) are merged
into `main` (P1.17), without a release of its own: they ship with the next release, see §15. Phase 2 (the GTK front
end) is wanted, its look is settled from a mockup, and it starts after that merge and
the spikes in §7.1, on a branch of its own until full parity. Short summary in `docs/PLAN.md` §10, "A GTK front end
for GNOME". The author's answers to the open questions are in §13 and as decisions D8–D13 in §1.

This document is written for whoever implements it, possibly without the conversation it came from. Every claim about
the code base was true at commit `deeec54` (release 0.11.3). Check it against the code before you rely on it.

---

## 1. Why, and what was decided

Kram's UI is PySide6 (Qt 6). On GNOME it looks like a foreign app (Fusion with a libadwaita palette, see
`kram/ui/theme.py`), and part of the GNOME audience stays away. The decisions so far:

| # | Decision | Date |
|---|---|---|
| D1 | **No shared widget abstraction** over Qt and GTK. It would be a small toolkit of our own at the level of their common denominator: Qt's item models and delegates and GTK 4's list models and factories work differently. It would be larger than a second front end and native nowhere. | 2026-11-21 |
| D2 | **No wxWidgets.** It is that same abstraction, and on Linux it uses GTK 3 only. | 2026-11-21 |
| D3 | **Two native front ends over one toolkit-free layer**: the existing Qt front end and a new GTK 4 + libadwaita one. | 2026-11-21 |
| D4 | **Phase 1 first**: move everything that is not widgets out of `kram/ui` into toolkit-free modules, with no visible change to the Qt front end. Worth doing even if phase 2 never comes. | 2026-11-21 |
| D5 | **Separate packages per front end**, so that nobody installs the other toolkit. Names: D9, §10. | 2026-11-21 |
| D6 | **GTK main menu**: a hamburger menu in the header bar by default. A classic menu bar (`Gtk.PopoverMenuBar`, the same File / Edit / Package / Settings / Help as in Qt) is a setting, hidden by default. Synaptic's users are old Linux hands who remember GTK 2 menus; GNOME's default is the header bar menu. | 2026-11-21 |
| D7 | **GTK sidebar view switch**: at the bottom of the sidebar, every view visible and one click away, as a **vertical `Adw.ToggleGroup`** (libadwaita's segmented control). Rejected: a dropdown (two clicks, views hidden), a linked column of `Gtk.ToggleButton`s (its corners render broken), separate flat buttons with gaps (less clearly a control). | 2026-11-21 |
| D8 | **The front ends conflict; no run-time choice.** Each front-end package ships its own `/usr/bin/kram`, written for its toolkit. Only one is installed at a time, so there is no selector and no "which desktop gets which" rule (former Q2). | 2026-11-21 |
| D9 | **Package names `kram-qt` + `kram-gtk` (+ `kram-common`), if and only if** an installed `kram` (≤ 0.11.x / the last single-package release) is replaced by `kram-qt` on a plain `dnf upgrade`, never by `kram-gtk`, and the upgrade does not turn off the tray checker. Verified in a container first (spike S10, §7.1). **If that does not hold: `kram` (Qt) + `kram-gtk`.** §10. | 2026-11-21 |
| D10 | **Rename `kram/ui` to `kram/qt`** as a separate mechanical commit at the end of phase 1 (former Q3). | 2026-11-21 |
| D11 | **Settings are defined once, for both front ends**: a registry in `kram/app` (§4.1a). A new setting added there shows up in both front ends' Settings menus with no front-end code. A setting meant for one toolkit only (Qt's toolbar style, GTK's menu bar) carries that toolkit, and the other front end ignores it. The GTK front end has, at least: "Clicking the status icon marks the likely action", "Watch Fedora Releases", "Show Menu Bar". | 2026-11-21 |
| D12 | **The GTK hamburger button is hidden while the menu bar is shown** (former Q5). Turning the menu bar off in Settings brings it back. | 2026-11-21 |
| D13 | **Releases** (former Q6): phase 1 (the whole extraction, incl. D10) has no visible change, so it gets **no release of its own**: it is squash-merged into `main` and ships with the next release that has a user-visible change (changed by the author on 2026-11-21, from "one normal release"). Then all GTK work happens on a separate branch until **full parity** with the Qt front end; only then is `kram-gtk` released, together with the package split (D9). No preview release. | 2026-11-21 |

Non-goals: a Flatpak, other package systems, a GNOME-Software-like store look, mobile/adaptive layouts (Kram is a
dense desktop tool, `docs/PLAN.md` §1), dropping or freezing the Qt front end.

---

## 2. Where the code stands (at 0.11.3)

| Area | Lines | Toolkit |
|---|---|---|
| `kram/core/` (catalog, worker, filters, search, marks, history, …) | ~4.0k | none. `core/mainloop.py` already defines `Post` and a plain `Signal`, written with `GLib.idle_add` in mind |
| `kram/helper/kram_helper.py` (root helper) | 1.2k | none |
| `kram/ipc/client.py` (`HelperClient`) | 147 | none: subprocess + threads + `Post`, core `Signal`s `event` / `failed` |
| `kram/notifier/` (tray checker) | ~540 | Gio/GLib (python3-gobject), reads `kram.conf` with `configparser` |
| `kram/instance.py` (single-instance D-Bus contract) | 16 | none |
| `kram/i18n.py` | 57 | none (gettext) |
| `kram/__main__.py` | 68 | Qt (QApplication, translators, single instance, `kram file.rpm`) |
| `kram/ui/` (34 modules) | ~8.1k | PySide6 throughout |

Qt classes used, by count (from `git grep`): QIcon 119, QLabel 83, QMessageBox 67, QWidget 48, QVBoxLayout 46,
QDialogButtonBox 42, QTreeWidgetItem 35, QSettings 34, QPushButton 34, QHBoxLayout 33, QPalette 29, QDialog 24,
QAbstractItemView 22, QMenu 20, QPainter 19, QFontDatabase 19, QTimer 17, QLineEdit 17, QModelIndex 16, QHeaderView 16,
QPlainTextEdit 14, QTreeWidget 13, QAction 13, QSplitter 12, QNetworkReply 11, QProcess 10, QDBusConnection 9,
QTreeView 8, QTextBrowser 8, QTableView 5, QSystemTrayIcon 1 (the tray itself is Gio now).

### 2.1 What in `kram/ui` is logic, not widgets

Module by module, what phase 1 moves out. Names are the current ones.

- **`package_model.py`** (386): `COL_*`, `HEADERS`, `HIDEABLE`, `ADVISORY_LABEL`, `REASON_LABEL`, `REASON_TIP`,
  `STATUS_LABEL`, `_STATUS_ORDER`, `SORT_KEYS`, `shown_advisories`, `advisory_tip`, `held_tip`, `lock_tip`,
  `blocked_tip`, `latest_evr`, `human_size`, `repo_text`, `MANY_MARKS`. Inside `PackageTableModel`: `rows`, `visible`,
  `_positions`, `basearch`, `_sort`, `_evr_rank`, `marks`, `blocked`, `optional`, `set_rows`, `set_blocked`,
  `set_blocked_reason`, `set_visible`, `set_sort_column`, `sort_column`, `index_of_key` (as a position), `_sorted`,
  and in `data()` the rules for every cell's text, tooltip, font (bold/italic), dimmed foreground, background (mark
  tint), alignment and icon *kind*. Qt keeps `rowCount`/`columnCount`/`headerData`/`data` as an adapter, plus
  `QFont`/`QColor`/`QIcon` creation.
- **`marking.py`** (249): `Marker` is a `QObject` with Qt `Signal`s. Everything in it is logic except:
  `_check_removal_dependents` shows a `QMessageBox` (becomes a port call, §4.3), and `fill_group_menu` builds a `QMenu`
  (becomes a function returning menu item data, §4.4). `GROUP_MENU` / `ENVIRONMENT_MENU` are data already.
- **`main_window.py`** (1122): the presenter hiding in the window. Logic to move: the load cycle (`reload`, `_on_loaded`,
  `_on_error`, `_on_blocked`, `_waiting_for_lock`), the filter pipeline (`_on_filter`, `_candidates` with its cache,
  `apply_filter` incl. the async Provides/File search with `_search_gen`, `_why_empty`, `_wider_searches`), sort state
  (`_user_sort`, the ranked/unsorted switch in `_show`), selection by key (`_current_key`, `_select_key` as "which
  position"), dependency navigation (`_on_link`, `navigate`, `go_back`, `history`), copy texts (`copy_names`,
  `copy_nevras`), the action enable state (`_busy`, `_update_actions`: a pure function of selection, snapshot, marks,
  busy, blocked), marks bookkeeping (`_marks_changed`, `mark_selected`, `unmark_selected`), version lock
  (`set_version_lock`), the apply/review flow (`apply`, `change_group`, `_review`, `_on_review_failed`, `_on_preview`
  incl. the `skip_unavailable` retry), helper runs (`refresh_metadata`, `refresh_repo_metadata`, `run_helper_and_reload`,
  `_helper_result` minus the dialog, `_clean_cache`), repos/COPR/cache/history/upgrade/notifier openers (the parts
  before and after their dialogs), undo (`undo_transaction`, `_report_undo` texts), status bar texts
  (`_update_status`), `EMPTY_HINTS`, `BLOCKED_ENTRY`, `DETAILS_TAB_KEY`, `FILES_VIEW_KEY`, settings save/restore of the
  toolkit-free keys, `_can_open_file` (minus Qt's `activeModalWidget`), `_dropped_rpm` (path check only).
- **`sidebar.py`** (265): `VIEWS`, `MAX_HISTORY`, `COLLAPSIBLE`, `_history_id`, and in `Sidebar`: `_snap`, `_entries`,
  `_view`, `_selected` (per view), `_expanded`, `history`, `marked`, `blocked`, `custom`, `set_snapshot`, `set_view`,
  `select`, `add_search`, `remove_search`, `clear_history`, `_drop_history`, `_history_entries`, `refresh_counts`,
  `refresh_marked_count`, `current_view`, `current_entry_id`, the entry building in `_rebuild` (which builder, the
  placeholder text, which entry becomes current, which parents are expanded, bold/italic rules) and the hide-empty
  rule in `_on_item`. Qt keeps the `QTreeWidget` filling and the buttons.
- **`details.py`** (264): `MAX_DEP_ITEMS`, `_date`, `_reference`, and the *content* of every tab (`_advisories_html`,
  `_blocked_html`, `show_package`'s description/general/dependencies/versions/changelog). Today it is HTML strings;
  phase 1 turns it into a small document model (§4.6) that Qt renders to the same HTML. The advisories-tab
  visibility/selection rule (`_wants_advisories`, `_other_tab`) is logic too.
- **`details_loader.py`** (89): all logic; only `QTimer` (→ scheduler port, §4.2) and the `DetailsTabs` calls
  (→ a details sink interface).
- **`search_bar.py`** (96): `DEBOUNCE_MS`, `HISTORY_IDLE_MS`, the timers and the `changed`/`submitted`/`settled`
  protocol, `text()` stripping, `set_query` without searching, `clear(quietly)`, the funnel-icon rule. Widgets stay.
- **`status_bar.py`** (72): `metadata_age`, and the texts of `show_catalog` / `show_counts` (incl. the
  missing-repositories tooltip).
- **`empty_list.py`** (65): already toolkit-free, but returns HTML. Return structured lines with links instead (§4.6);
  Qt renders HTML.
- **`custom_filters.py`** (123): `SETTINGS_KEY`, `PREFIX`, `SEARCH_FIELDS`, load/save, `queries`, `resolve_missing`,
  `_resolve`, `new_from_view` (naming rule), the delete flow (confirmation → port). The dialog stays per toolkit.
- **`markings_file.py`** (75): file I/O and the report texts. File choosers and message boxes → ports.
- **`release_watch.py`** (87): all logic, but uses `QNetworkAccessManager`, `QAction` and `QSettings` (→ net helper,
  settings store, plain state + signal).
- **`actions.py`** (193): the *definitions* (id, text, icon name, shortcut(s), tooltip, scope: window or table) are
  data; `fill_package_menu` / `fill_menu_bar` are menu *structures*. Phase 1 moves the definitions and structures to
  `kram/app/actions.py` as data; Qt builds `QAction`s from them, GTK builds `Gio.SimpleAction`s and `Gio.Menu`s.
  Qt-only: `status_click` stays a setting in both; toolbar styles (`toolbar.py`) are Qt-only.
- **`links.py`**, **`files.py`**: `WEB_SCHEMES`, the scheme check, `FILE_MANAGER` / the D-Bus call shape. Opening
  goes through a port.
- **`single_instance.py`**: Qt side of `kram/instance.py`, stays Qt. GTK does its own (§7.4).
- **`theme.py`**: Qt only (GTK needs none: libadwaita follows the desktop).
- **`icons.py`** (346), **`group_icons.py`** (114): drawing stays per toolkit. Move the *data* out: colours
  (`ADVISORY_COLOR`, `MARK_BACKGROUND`, the origin styles), `ORIGIN_LABEL`, the group id → icon names table
  (`group_icons`' `_DESKTOP`… `_GENERIC`, `_ALL`) and `status_filter_icon`'s id → glyph mapping.
- Dialogs: their pure helpers move to `kram/app` (already pure today: `apply_dialog.signed_size`, `_rec_label`,
  `shortfall`, `groups_only_note`, `removal_warning`; `history_dialog.counts_text`, `comps_key`; the text builders of
  `install_dialog` (`_state_line`, `_signature_line`, `_requirement_line`), `upgrade_dialog` (`_removal_line`, the
  report keys), `progress_dialog` (`_helper_text`, `_action_text`, the event → state machine in `_on_event`,
  `_on_download`, `_on_rpm`, `_set_rpm_position`, `_finish`), `cache_dialog` (row descriptions, `describe`),
  `repos_dialog` (`changes`, `_packages_blocker`, `_removal_blocker`), `filters_dialog` (`_unique`, the condition
  editing rules), `notifier_dialog` (the state it reads and the texts). The widgets stay.

### 2.2 Things in the Qt code that GTK 4 cannot do the same way

1. **Modal `exec()`**. 24 `QDialog`s and 67 `QMessageBox` uses, many in the middle of a flow: `_on_preview` runs
   `ApplyDialog.exec()`, then `_run_helper` runs `ProgressDialog.exec()`, then unmarks and reloads, all in one function.
   GTK 4 has no nested main loop for dialogs (`gtk_dialog_run` is gone, `Gtk.Dialog` is deprecated). Every such
   flow must become **continuation style**: show, and continue in a callback. This is the largest change in phase 1
   and the reason the flows move into `kram/app` written that way from the start (§4.3). The Qt adapter may still
   implement a port with `exec()` and call the continuation at once: Qt's behaviour does not change.
2. **QSettings**. `~/.config/kram/kram.conf` is QSettings' INI format. Binary values (`window/geometry`,
   `window/hsplit`, `window/vsplit`, `table/header-v2`, `history/geometry`, `history/splitter`) are `@ByteArray(…)`
   blobs only Qt can read. The tray already reads the file with `configparser` (`kram/notifier/__init__.py`,
   `stale_days`). Plan: §4.1.
3. **HTML**. `QTextBrowser` renders HTML in Description, General, Dependencies, Advisories, Changelog, What's New, the
   install dialog's tabs and the empty list's text. GTK has no HTML view (WebKit is out of the question). Plan: a
   neutral document model, §4.6.
4. **QNetworkAccessManager** in `release_watch.py`, `copr_dialog.py`, `upgrade_dialog.py`; **QProcess** in
   `install_dialog.py` (`rpm -V`), `notifier_dialog.py` (systemctl), `upgrade_dialog.py` (launching Discover / GNOME
   Software); **QtDBus** in `single_instance.py`, `files.py`, `notifier_dialog.py`. Plan: toolkit-free helpers, §4.5.
5. **The package table**: `QAbstractTableModel` over an index list, sorted by our own code, with a delegate that
   highlights the hovered row, tinted marked rows, per-cell tooltips, click on the status cell opening a menu, header
   menu to hide columns, header state saved. GTK 4 equivalent: `Gtk.ColumnView`. Plan and spikes: §7.1, §7.3.

---

## 3. Target layout

```
kram/
  core/          unchanged role: libdnf5, models, filters, search, marks…; new: settings.py, net.py, proc.py (§4)
  app/           NEW, toolkit-free: presenters, view state, texts, action/menu definitions, ports (§4)
  ui/ → qt/      the Qt front end; renamed to kram/qt at the end of phase 1 (D10), with its own __main__.py
  gtk/           NEW in phase 2: the GTK 4 + libadwaita front end, with its own __main__.py
  helper/ ipc/ notifier/ instance.py i18n.py   unchanged
```

`kram/__main__.py` goes away: each front end has its entry point (`kram.qt.__main__:main`,
`kram.gtk.__main__:main`), and each front-end package installs its own `/usr/bin/kram` pointing at it (§9).

Rules for `kram/app`:

- **No toolkit imports**: no `PySide6`, no `gi` (not even Gio). Enforced by a test (step P1.0) that imports every
  `kram.app` module with `PySide6` and `gi` made unimportable (`sys.modules[...] = None` in a subprocess) and fails on
  any import error. `kram/core` gets the same test, except that `core/net.py` and `core/proc.py` may use only the stdlib.
- Signals: `kram.core.mainloop.Signal`. Main-loop hand-off: `kram.core.mainloop.Post`. Timers: the `Scheduler` port
  (§4.2). User interaction: ports (§4.3).
- Everything in `kram/app` runs on the GUI thread, as the Qt code does today. Background work goes through
  `DnfWorker` (libdnf5) or the net/proc helpers, which report back through `Post`.
- Texts are translated with `kram.i18n` as today. **Keep the msgids identical** when moving code: every `.po` catalog
  must stay complete (the tests fail on an incomplete catalog or a fuzzy entry, `tests/test_i18n.py`). A moved string
  keeps its translations; `scripts/i18n.sh update` only updates the source references.
- Docstrings and comments follow the house style: explain why, in full sentences, English.

---

## 4. The toolkit-free layer in detail

### 4.1 Settings: `kram/core/settings.py`

A small store over `~/.config/kram/kram.conf` that **reads and writes QSettings' INI format** for plain values, so
both front ends and the tray share one file and existing users keep their settings.

- API: `Settings(path=None)`; `get(key, default, type=str|int|bool|float)`, `set(key, value)`, `remove(key)`,
  `sync()`. Keys are QSettings keys (`"search/mode"` → section `[search]`, key `mode`; a key without a slash lives in
  `[General]`).
- Values: `str`, `int`, `bool` (written `true`/`false` like Qt), `float`, and JSON strings (as today:
  `search/history`, `filters/custom`). **Never** write `@ByteArray`/`@Variant` from Python. Leave keys you do not know
  untouched (a Qt-only binary key must survive a GTK session).
- Escaping: match QSettings' INI escaping for strings (backslash escapes, quoting of values with leading/trailing
  spaces, `;`, `,`, `=`, `"`; commas mean a string list to QSettings, so a string containing a comma must be
  quoted). Find the exact rules in Qt's `qsettings.cpp` (`iniEscapedString`, `iniUnescapedStringList`) and copy
  them. Do not guess.
- Concurrency: one Kram runs at a time (single instance), but the tray reads, and Qt keeps its own in-memory copy.
  Write by read-modify-write of the whole file under `fcntl.flock`, into a temp file + `os.replace`. Qt front end:
  shared keys go through `core.settings`; Qt-only binary keys stay in `QSettings`. Make sure the two do not
  overwrite each other: QSettings re-reads the file on `sync()` when its mtime changed and merges only *its* changed
  keys. **Verify this with a test**, not from memory.
- Tests (with PySide6 present, skipped otherwise): every value type round-trips Python → QSettings and QSettings →
  Python, including non-ASCII (Ukrainian), commas, quotes, leading spaces, empty strings, a JSON list; a Qt-written
  `@ByteArray` key survives a Python write; concurrent writes from both keep both keys.
- Move every toolkit-free key to it. Current keys (from `git grep`): `details/files-view`, `details/tab` (old),
  `details/tab-name`, `distro/running_eol`, `distro/target`, `distro/watch`, `export/dir`, `filters/custom`,
  `install/dir`, `markings/dir`, `progress/auto_close`, `search/history`, `search/mode`, `sidebar/entry`,
  `sidebar/view`, `table/status_click`, `update_checker/stale_days`. Qt-only: `window/geometry`, `window/hsplit`,
  `window/vsplit`, `table/header-v2`, `table/advisory-column`, `table/download-column`, `history/geometry`,
  `history/splitter`, `toolbar/style`. GTK-only (new, phase 2): `gtk/window` (width, height, maximized as JSON),
  `gtk/panes` (sidebar and details positions), `gtk/columns` (JSON: ordered list of `{id, width, visible}`),
  `gtk/history-window`, `gtk/menubar` (bool, default false).
- `kram/notifier/__init__.py` `stale_days()` switches to `core.settings` (it reads the same file today).

### 4.1a The preferences registry: `kram/app/preferences.py` (D11)

The user-facing settings are declared once. Both front ends build their Settings menu (and any settings dialog) from
the registry, so a new setting appears in both with no front-end code; the store (§4.1) holds the values.

```python
@dataclass(frozen=True)
class Pref:
    key: str                          # the settings key, e.g. "table/status_click"
    kind: Literal["bool", "choice", "int"]
    default: object
    label: str                        # translated, as shown in the menu
    tip: str = ""
    choices: tuple[tuple[str, str], ...] = ()   # (value, label) for "choice"
    toolkits: frozenset[str] = frozenset({"qt", "gtk"})   # a front end not listed ignores the setting entirely
    visible: Callable[[], bool] = lambda: True  # e.g. "Watch Fedora Releases" only on Fedora (distro.running_release())
    section: str = "settings"         # where in the Settings menu it goes (a separator between sections)

PREFS: tuple[Pref, ...]               # in menu order
def value(pref) / set_value(pref, v)  # through core.settings; set_value emits `changed(key)` (a core Signal)
```

- Entries at the start: `table/status_click` (bool, false, both), `distro/watch` (bool, true, both, visible on Fedora
  only), `toolbar/style` (choice, "system", **qt only**: the four `TOOLBAR_STYLES`), `gtk/menubar` (bool, false,
  **gtk only**, label "Show Menu Bar"). `update_checker/stale_days` lives in the Update Notifications dialog, not the
  menu: give `Pref` a `section="notifications"` and let that dialog read it from the registry too.
- Qt: `WindowActions` builds a checkable `QAction` per bool pref (a `QActionGroup` per choice pref) from `PREFS` where
  `"qt" in toolkits`, wired to `set_value`; the Toolbar submenu becomes the choice pref's group. GTK: a stateful
  `Gio.SimpleAction` per pref (`win.pref-<key>`), menu items from the same list.
- A test walks `PREFS` and checks that both front ends' menus contain exactly the prefs of their toolkit (Qt test now,
  GTK test in phase 2), so a new pref cannot be forgotten in one of them.
- Unknown keys in `kram.conf` (a GTK-only key in a Qt session and the other way round) are left alone, never deleted.

### 4.2 Scheduler port

Timers used today: search debounce 150 ms and history idle 1500 ms (`search_bar.py`), details delay 120 ms
(`details_loader.py`), files filter 150 ms (`file_list.py`), the sidebar's deferred rebuild (`QTimer.singleShot(0)`),
the drop handler's deferral, the progress/upgrade dialogs' timers.

```python
class Timer(Protocol):
    def start(self) -> None: ...      # (re)start: a pending call is pushed back
    def stop(self) -> None: ...
    @property
    def active(self) -> bool: ...

class Scheduler(Protocol):
    def timer(self, ms: int, fn: Callable[[], None]) -> Timer: ...   # single-shot, restartable
    def later(self, fn: Callable[[], None]) -> None: ...              # as soon as the loop is idle (singleShot(0))
```

Qt: `QTimer(singleShot=True, interval=ms)`; GTK: `GLib.timeout_add(ms, …)` with source removal on stop/restart
(return `GLib.SOURCE_REMOVE`), `GLib.idle_add` for `later`. Tests: a `FakeScheduler` that runs timers on demand
(`advance(ms)`), so the debounce and "details wait for the cursor to rest" tests need no event loop.

### 4.3 Interaction ports (continuation style)

Everything the logic needs from the user goes through one object per front end, passed to the presenters. Every
method returns at once and calls a continuation later (Qt may call it before returning). Proposed surface. Derive the
final list from the code while moving it, and keep it as small as the code allows:

```python
class Ui(Protocol):
    # messages
    def info(self, title: str, text: str, details: str = "") -> None: ...
    def warn(self, title: str, text: str, details: str = "") -> None: ...
    def error(self, title: str, text: str, details: str = "") -> None: ...
    def status(self, text: str, timeout_ms: int = 0) -> None: ...          # the status bar's transient message
    def ask(self, q: Question, done: Callable[[str | None], None]) -> None: ...
        # Question: title, text, informative, details, buttons [(id, label, role)], default id, icon kind
        # done(id) with the button pressed, None for cancel/close
    # files
    def choose_open_file(self, title, start_dir, filters, done: Callable[[str | None], None]) -> None: ...
    def choose_save_file(self, title, start_path, filters, done: Callable[[str | None], None]) -> None: ...
    # desktop
    def open_web_link(self, url: str) -> bool: ...
    def show_in_file_manager(self, path: str) -> None: ...
    def copy_text(self, text: str) -> None: ...
    # dialogs that are flows of their own; each resolves with its result
    def review_changes(self, preview, request, basearch, resolve, done: Callable[[ReviewResult | None], None]) -> None: ...
    def run_helper(self, request: dict, title: str, done: Callable[[dict | None], None]) -> None: ...
    def open_repos(self, …, done) -> None: ...      # ReposDialog: show_repo / remove_repos / changes
    def open_copr(self, …) -> None: ...
    def open_cache(self, …) -> None: ...
    def open_history(self, …) -> None: ...          # non-modal
    def open_upgrade(self, …) -> None: ...
    def open_notifications(self) -> None: ...
    def open_install(self, path, …, done: Callable[[bool], None]) -> None: ...   # done(changed_system)
    def edit_filters(self, …, done) -> None: ...
    def about(self) -> None: ...
    def is_modal_open(self) -> bool: ...            # _can_open_file's activeModalWidget check
```

Flows to rewrite in this style (the order of events must stay exactly as today; the main-window tests in
`tests/test_main_window.py` pin most of it):

1. Apply: `apply` → `_review` (sets `_reviewing`) → resolve on the dnf thread → `_on_preview` → (not ok: `ask` with
   "Undo What Is Possible…" / "Show Locked Packages" / OK; the `skip_unavailable` probe first for a revert) →
   `review_changes` → `run_helper` → unmark the applied keys (only `keys` captured at request time) → `reload`. Tests:
   `test_apply_twice_before_the_preview_resolves_once`, `test_no_refresh_while_the_marks_are_resolved`,
   `test_a_failed_resolve_clears_the_status_and_allows_a_retry`, `test_a_failed_apply_reloads_and_keeps_the_marks`,
   `test_a_successful_apply_unmarks_only_what_it_applied`, `test_a_late_result_for_a_closed_apply_dialog_is_dropped`.
2. Removal dependents (`Marker._check_removal_dependents`): `ask` with Mark / Cancel; Cancel restores the marks
   before the removal, as in Synaptic.
3. Version lock: unmark the upgrades/downgrades it blocks, `status` message, `run_helper` → reload.
4. Repositories: counts on the dnf thread → `open_repos` → show packages / remove (reopen after reload via a
   one-shot `catalog_loaded` connection) / enable changes.
5. Undo: `package_states` on the dnf thread → `plan_undo` → `Marker.mark_undo` → close history → select Marked →
   report (`info`/`warn` with details) or a status message.
6. Quit with unapplied marks: `ask` (Yes/No). GTK's close-request must return `True` (stop) and then close again
   from the continuation; the presenter exposes `can_close(done: Callable[[bool], None])`.
7. Markings read/save, CSV export (file choosers, then errors through `error`).
8. Custom filter delete (`ask`), edit (`edit_filters`).
9. Install file (from the menu, a drop, `kram file.rpm`).

### 4.4 Actions and menus as data: `kram/app/actions.py`

```python
@dataclass(frozen=True)
class ActionDef:
    id: str                      # "reload", "mark.install", "mark-upgrades.security", …
    label: str                   # translated, with no mnemonic (Qt adds "&" to menu titles only)
    icon: str | None             # freedesktop icon name, as today (Qt: QIcon.fromTheme; GTK: the -symbolic name if present)
    shortcuts: tuple[str, ...]   # neutral form "Ctrl+R", "F5", "Ins", "Del", "Alt+Left", "Ctrl+Shift+Z"
    tip: str = ""
    scope: Literal["window", "table"] = "window"
    checkable: bool = False      # status_click, watch releases, show menu bar (GTK)

@dataclass(frozen=True)
class MenuItem:                  # a menu structure: items, separators, submenus
    action: str | None = None
    submenu: "Menu | None" = None
    separator: bool = False
```

- Move every definition from `WindowActions.__init__` verbatim (texts, icons, shortcuts, tips, the table scope of
  copy/mark/unmark/lock/unlock/show_in_history/why_blocked). `QKeySequence.StandardKey.Find` = `Ctrl+F`, `Quit` =
  `Ctrl+Q`.
- Menu structures: `package_menu()` (what `fill_package_menu` adds), `menu_bar()` (what `fill_menu_bar` adds, the
  Settings menu's extra settings and the Qt-only Toolbar submenu marked as such), `mark_upgrades_menu()`,
  `group_menu(group, busy)` (today `Marker.fill_group_menu`: label, icon, enabled, tooltip per item; the callback is
  `(group, action, optional)`), `sidebar_menu(entry, …)` (today `MainWindow._sidebar_menu`), the dynamic
  `downgrade_menu(rows, details)` (today `_fill_downgrade_menu`: "(loading…)", "No older versions…", `evr (repo)`).
- Enable state: `action_state(selection, snapshot, marks, blocked, busy, has_history_dialog, upgrades_of_kind,
  unneeded, can_open_file) -> dict[str, (enabled, visible)]`: a pure function holding exactly the rules of
  `_update_actions` and `set_upgrades_available`. Its own unit tests: one per rule. The existing
  `test_catalog_actions_are_disabled_until_it_is_loaded` and `test_mark_upgrades_icon_follows_whether_there_is_anything_to_mark`
  keep passing.
- The Qt "Mark All Upgrades" icon swap (`update-medium` / `update-none`) is Qt-only; GTK uses one symbolic icon.

### 4.5 Network and processes: `kram/core/net.py`, `kram/core/proc.py`

- `net.fetch(url, *, timeout_s, headers, post, done, failed, cancel: threading.Event | None = None)`: `urllib.request`
  on a small daemon `ThreadPoolExecutor` (not the dnf worker: a slow Copr search must not hold libdnf5 jobs),
  results through `post`. Same User-Agent as `upgrade_dialog.api_request` today (read its docstring for why: Bodhi
  answers a browser-like User-Agent differently). JSON helper `fetch_json`. Errors: timeout, HTTP status, network,
  JSON → one exception type with a message for the UI.
- Replace `QNetworkAccessManager` in `release_watch.py` (Bodhi, 15 s), `copr_dialog.py` (search, 60 s: "the Copr
  search API is slow, 10–20 s per query"), `upgrade_dialog.py` (COPR chroots per project). Keep the "last result
  stays on failure" and "late reply for a closed dialog is dropped" behaviours (`test_a_failed_check_keeps_the_last_result`).
- `proc.run(argv, *, post, done(code, stdout, stderr), env=None)` and `proc.spawn_detached(argv)`: replace `QProcess`
  in `install_dialog._start_verify` (`rpm -V`, with its environment), `notifier_dialog._enable_fedora_timer`
  (systemctl), `upgrade_dialog._launch_program` (Discover / GNOME Software, in its own scope as now).
- D-Bus calls made today with QtDBus outside `single_instance.py`: `files._show_items_over_dbus`
  (FileManager1.ShowItems) and `notifier_dialog._bus_owner_pid`. Put them behind the `Ui` port
  (`show_in_file_manager`) and a small `bus` port. GTK implements them with Gio. Qt may keep QtDBus.

### 4.6 A document model instead of HTML: `kram/app/doc.py`

Small and exactly what the tabs need. No general rich text.

```python
Span = Text | Bold | Italic | Mono | Small | Link | Colored   # inline, nestable where used today
#   Link(kind: "pkg" | "dep" | "web", target: str, children)
#   Colored(role: "error" | "warning" | "dim", children)        # roles, not colours: each front end maps them
Block = Heading(level, spans) | Para(spans) | Table(rows: [(label_spans, value_spans)]) | Bullets(items, more: int)
       | Section(title, count, items: [Span], kind) | Rule() | Preformatted(text)
Doc = list[Block]
```

- Builders, moved from `details.py` with the same content and order: `description_doc`, `general_doc`,
  `dependencies_doc` (incl. `MAX_DEP_ITEMS` and "…and {n} more"), `advisories_doc` (incl. the held-back header and
  `_reference`), `blocked_doc`, `changelog_doc` (incl. the "available for installed packages only" note), versions as
  rows (not a doc: `[(evr, repo, state, bold, dimmed)]`), What's New (`whats_new_doc`), the install dialog's tabs and
  header lines, `empty_list.explain` (→ a Doc with `Link(kind="action", target=ALL|DESCRIPTIONS|RELOAD|REPOS|RETRY)`).
- Qt: `kram/ui/doc_html.py` renders a Doc to **the same HTML as today**. Prove it: before switching, add tests that
  render the current HTML for representative rows (the fixtures of `tests/test_advisories.py`,
  `tests/test_main_window.py::test_long_dependency_lists_are_cut`, an empty-list case of `tests/test_empty_list.py`)
  and compare byte for byte after the switch. Where byte-identical is impractical, compare the visible text plus link
  targets.
- GTK: `kram/gtk/doc_view.py` renders a Doc to a vertical `Gtk.Box` of `Gtk.Label`s with Pango markup (links as
  `<a href="pkg:…">`, handled in `activate-link`, which returns True for our kinds). Long sections
  (Dependencies, up to 7 sections × 1000 items) must not build thousands of widgets: render each `Section` as one
  label with one link per line, and measure it in spike S6 (§7.1). If it is slow, use a `Gtk.ListView` per section.
  Escape every text with `GLib.markup_escape_text`.

### 4.7 Presenters

| New module | From | Holds |
|---|---|---|
| `app/columns.py` | `package_model.py` | column ids, headers, hideable, labels/tips, sort keys + `sorted_positions`, and `cell(r, col, ctx) -> Cell(text, tooltip, icon: IconRef \| None, bold, italic, dimmed, align_right)`, `row_tint(r, marks) -> Action \| None`. `ctx` holds basearch, marks, blocked, optional |
| `app/package_list.py` | `package_model.py` | `PackageList`: rows, visible positions, sort (column, ascending) or ranked, positions cache, evr ranks, marks, blocked, optional; signals `reset`, `rows_changed(keys \| None)` (with `MANY_MARKS` coalescing), `sorted`. Positions are ints, not QModelIndex |
| `app/marking.py` | `marking.py` | `Marker` without Qt; `group_menu()` data |
| `app/search.py` | `search_bar.py` | `SearchController`: text, mode, debounce + history timers via the scheduler, `changed`/`submitted`/`settled` signals, `set_query`, `clear(quietly)`, `funnel` state |
| `app/sidebar.py` | `sidebar.py` | `SidebarModel`: views, entries per view, selection per view, expanded set, history, hide-empty rule; signals `entries_changed(view, entries, current_id, expanded_ids)`, `filter_changed(entry)` |
| `app/details.py` | `details.py`, `details_loader.py` | `DetailsLoader` (scheduler instead of QTimer), doc builders, the advisories-tab rule; a `DetailsSink` protocol the front end implements |
| `app/browser.py` | `main_window.py` | `Browser`: the main window's state and flows (§2.1 list), driving `PackageList`, `SidebarModel`, `SearchController`, `Marker`, `DetailsLoader`, the status texts and the `Ui` port |
| `app/status.py` | `status_bar.py` | `metadata_age`, `counts_text`, `missing_repos_text/tip` |
| `app/release_watch.py` | `release_watch.py` | `ReleaseWatcher` on `core.net` + `core.settings`; state `target`, `running_eol`, signal `changed` |
| `app/custom_filters.py` | `ui/custom_filters.py` | load/save/queries/resolve/new_from_view/delete flow |
| `app/markings.py` | `markings_file.py` | read/save + report texts |
| `app/progress.py` | `progress_dialog.py` | helper event → progress state (stage text, bars, counts, log lines, question, final result); the dialog only shows the state |
| `app/apply_review.py` | `apply_dialog.py` | `signed_size`, `shortfall`, `groups_only_note`, `removal_warning`, recommendation state and the re-resolve on toggle, the equivalent command |
| `app/history.py` | `history_dialog.py` | chunked loading state, filter by name, `counts_text`, `comps_key`, undo availability |
| `app/install.py` | `install_dialog.py` | the dialog's state machine (catalog → read → target → resolve → verify), header lines, tabs as docs, the request |
| `app/repos.py`, `app/copr.py`, `app/cache.py`, `app/upgrade.py`, `app/notifier.py`, `app/filters_edit.py` | the dialogs | their state, rules and texts; each dialog becomes a view over it |
| `app/icons.py` | `icons.py`, `group_icons.py` | colours, labels and the icon *references*: `IconRef = ("status", Status) \| ("mark", Action) \| ("locked", installed) \| ("origin", Origin) \| ("advisory", level \| None) \| ("held", level) \| ("blocked",) \| ("group", group_id) \| ("filter", entry_id) \| ("theme", names)`. Each front end draws or looks up an `IconRef` |

---

## 5. Phase 1 — steps

Work on a feature branch (`gtk-prep` or similar), one commit per step. After **each** step: `ruff check .`,
`QT_QPA_PLATFORM=offscreen pytest` all green, and the Qt app starts and behaves the same (run it: `python3 -m kram`).
No user-visible change in phase 1, so no `Changelog:` trailers, except where a step fixes something on the way
(then a trailer for that fix). Squash-merge into `main` locally when the author agrees. Do not push without asking.

| Step | What | Done when |
|---|---|---|
| P1.0 | `kram/app/__init__.py`; the import-isolation test for `kram.core` and `kram.app` (§3) | the test passes and fails if a PySide6 import is added to `kram/app` |
| P1.1 | `core/settings.py` + tests (§4.1); move every toolkit-free key to it in the Qt code and in `notifier.stale_days` | round-trip tests pass both ways; an existing `kram.conf` from 0.11.3 (make a fixture from a real one) reads the same values |
| P1.2 | `Scheduler` port, Qt implementation, `FakeScheduler` for tests | `search_bar`, `details_loader`, `file_list`, `sidebar`'s deferral use it; their tests pass |
| P1.3 | `app/columns.py`, `app/icons.py` (data only); `PackageTableModel.data` delegates to `cell()` | `tests/test_package_view.py`, `test_advisories.py` pass unchanged |
| P1.4 | `app/package_list.py`; `PackageTableModel` becomes an adapter that forwards `reset`/`rows_changed`/`sorted` to Qt signals | `test_marking_every_row_is_one_change_and_finds_rows_at_once`, `test_a_reset_does_not_cost_more_with_more_rows` pass; a perf check with `scripts/perf_search.py` shows no slowdown (> 10 % on any measured step is a regression) |
| P1.5 | `app/actions.py` (definitions, menu structures, `action_state`) and `app/preferences.py` (§4.1a); Qt `WindowActions` builds `QAction`s from both | the menus look identical (compare text, order, shortcuts by a test that walks the Qt menu bar against the data); the prefs test of §4.1a passes for Qt |
| P1.6 | `Ui` port (§4.3) with the Qt implementation (`kram/ui/qt_ui.py`): message boxes, file dialogs, links, clipboard | — |
| P1.7 | `app/marking.py` (`Marker` without Qt); removal dependents through `Ui.ask` | `tests/test_marks.py` and the marking tests of `test_main_window.py` pass |
| P1.8 | `app/search.py`; Qt `SearchBar` keeps only the two widgets | `test_a_provides_search_typed_over_is_skipped_not_run` passes |
| P1.9 | `app/sidebar.py`; Qt `Sidebar` draws `SidebarModel`'s entries | `tests/test_sidebar_tree.py`, `test_environments_are_a_tree`, `test_marking_recounts_only_the_marked_entry` pass |
| P1.10 | `app/doc.py`, `kram/ui/doc_html.py`; details tabs, empty list, What's New through docs | the HTML comparison tests (§4.6) pass |
| P1.11 | `app/details.py` (loader + builders) | `test_details_wait_for_the_cursor_to_rest`, `test_long_dependency_lists_are_cut`, the blocked-reason tests pass |
| P1.12 | `app/status.py`, `app/browser.py`: the flows of §4.3 in continuation style; `MainWindow` becomes a view of `Browser` | all of `tests/test_main_window.py` passes; the window class is mostly building widgets and wiring |
| P1.13 | `core/net.py`, `core/proc.py`; switch `release_watch`, `copr_dialog`, `upgrade_dialog`, `install_dialog`, `notifier_dialog` | their tests pass; manual check: Copr search, Bodhi check (Reload with "Watch Fedora Releases"), `rpm -V` on reinstall, enabling the timer |
| P1.14 | the dialogs' logic modules (table in §4.7), one commit per dialog | each dialog's tests pass; the dialog modules shrink to widgets |
| P1.15 | cleanup: dead code, docstrings, `docs/PLAN.md` §3 repository layout updated, `docs/GTK_FRONTEND.md` marked "phase 1 done" with what changed from this plan | review with the author |
| P1.16 | rename `kram/ui` → `kram/qt` (D10), one mechanical commit: `git mv`, imports, tests, `pyproject.toml` script target (`kram.qt.__main__:main`), `kram/__main__.py` → `kram/qt/__main__.py`, the spec's `%check`, `scripts/i18n.sh` source paths (the `.pot` references change, the msgids do not), docs | `ruff`, all tests, `scripts/rpm_check.sh` pass; `python3 -m kram.qt` runs |
| P1.17 | merge (D13): squash-merge `gtk-prep` into `main`, no release of its own; phase 1 ships with the next release. Still one `kram` package | merged; the author has run the branch on their machine |

Measure as you go: `kram/ui` should end at roughly half its size. If a step makes the code harder to read than it was,
stop and discuss it. The goal is thinner widget code, not indirection for its own sake.

---

## 6. Phase 2 — the GTK front end: look

From the mockup reviewed on 2026-11-21 (static, fake data). The mockup script is not in the repository. Rebuild it
from this description if needed.

- **Window**: `Adw.ApplicationWindow`, title "Kram", subtitle "Package Manager" (`Adw.WindowTitle`). Content:
  `Adw.ToolbarView` with the header bar (and the optional menu bar) as top bars and the status bar as bottom bar.
- **Header bar** (`Adw.HeaderBar`), start: Reload (`view-refresh-symbolic`, tooltip with Ctrl+R),
  Mark Upgrades (`Adw.SplitButton`: click = Mark All Upgrades, the arrow = `mark_upgrades_menu()`: security /
  critical+important / security+bug fix), Apply (`suggested-action`, label "Apply", enabled only with marks).
  End: main menu (`Gtk.MenuButton`, `open-menu-symbolic`, `primary=True` so F10 opens it; hidden while the menu bar is
  shown), COPR, Repositories, the "Fedora N" release button when there is a target (§`app/release_watch.py`), search
  mode (`Gtk.DropDown`: Name / Name + summary / Description / Provides / File, with the same tooltip as Qt) linked
  with the search field (`Gtk.SearchEntry`, placeholder "Search (Ctrl+F)", funnel icon while filtering).
- **Menu bar** (pref `gtk/menubar` "Show Menu Bar", in Settings, default off, D6, D11): `Gtk.PopoverMenuBar` from
  `menu_bar()` under the header bar; while it is shown the hamburger button is hidden (D12). Same items as the hamburger menu, which has File / Edit / Package / Settings as submenus and Help's
  items as a last section.
- **Body**: `Gtk.Paned` (sidebar | right), right = `Gtk.Paned` vertical (package list | details); the details cannot
  be collapsed out of sight (`shrink_end_child=False`, a minimum height), as in Qt.
- **Sidebar**: a `Gtk.ListBox` with `navigation-sidebar` style (or a `Gtk.ListView` over a `Gtk.TreeListModel` for
  the Environments tree, whichever spike S5 favours). Rows: icon (painted status box, origin badge, group icon), label,
  count right-aligned and dimmed (`tnum`). Bold "All …" and installed groups, italic optional groups, tooltips. Below,
  separated by a line: **vertical `Adw.ToggleGroup`**, homogeneous, one `Adw.Toggle` per view with icon and label:
  Status (`checkbox-checked-symbolic`), Origin (`network-server-symbolic`), Groups (`view-grid-symbolic`),
  Environments (`computer-symbolic`), Search Results (`edit-find-symbolic`), Custom Filters (`object-select-symbolic`).
  Check every icon name exists in Adwaita's symbolic set: Adwaita lacks `emblem-ok-symbolic` and `funnel-symbolic`.
  Right-click on an entry: `sidebar_menu()` as a `Gtk.PopoverMenu`.
- **Package list**: `Gtk.ColumnView` with the `data-table` style, multi-selection, reorderable and resizable columns,
  no separators. Columns as in Qt (S, origin, Package, Installed version, Reason, Latest version, Update type,
  Repository, Installed size, Download size (hidden by default), Summary (expands)). Status and origin cells draw
  `IconRef`s (§7.3); the latest-version cell shows the advisory / held / blocked mark before the version; bold
  upgradable versions, italic held versions and optional names, dimmed blocked/held; size columns right-aligned with
  tabular numbers. Marked rows tinted per action (CSS class per row via `row_factory`, colours from
  `MARK_BACKGROUND` translated to CSS, a dark-mode variant). Tooltips per cell from `cell()`. Empty list: a
  centred label with links over the list (`Gtk.Overlay`), from the empty-list doc.
- **Details**: `Adw.ViewSwitcher` (wide policy, start-aligned) over an `Adw.ViewStack`: Description, General,
  Advisories (visible only for upgrades with advisories; `needs-attention` dot), Dependencies (`needs-attention` while
  blocked), Files, Versions, Changelog. Tab contents from the docs (§4.6); Files: tree (`Gtk.TreeListModel` +
  `Gtk.TreeExpander`) or list, filter entry, the same context menu (copy path, show in file manager); Versions: a
  small `Gtk.ColumnView`.
- **Status bar**: a bottom bar box: counts text (tooltip with timings), the missing-repositories warning as a link
  button (opens Repositories), metadata age dimmed on the right. Transient messages (`Ui.status`) replace the counts
  text for their timeout, as Qt's `showMessage` does. No `Adw.Toast`s: Kram keeps a Synaptic-like status line.
- **Dialogs**: `Adw.Dialog` (or `Adw.Window` for the non-modal History) with an `Adw.ToolbarView` + header bar; the
  confirm buttons at the bottom right as in Qt (Apply dialogs are reviews, not settings). Message boxes:
  `Adw.AlertDialog` with responses; "details" in an `Gtk.Expander` as the extra child. Notifier and Cleanup settings
  may become `Adw.PreferencesDialog` pages if that reads naturally; decide per dialog when building it.
- **Keyboard**: the same shortcuts as Qt (from `ActionDef.shortcuts`): app-level accelerators with
  `Gtk.Application.set_accels_for_action`; table-scoped ones (Ctrl+C, Ctrl+Shift+C, Ins, Del, Ctrl+Z, …) in a
  `Gtk.ShortcutController` on the column view (scope local), so the search field keeps them.
- **Theme**: nothing to do: libadwaita follows the desktop's light/dark and accent colour. Test both.

---

## 7. Phase 2 — the GTK front end: building it

### 7.1 Spikes first (each a throwaway script under `scripts/spikes/` or the scratchpad, results written into §14)

| Spike | Question | Pass |
|---|---|---|
| S1 | `Gtk.ColumnView` over **70k rows**: a Python `GObject` implementing `Gio.ListModel` (`do_get_item_type`, `do_get_n_items`, `do_get_item` creating light items on demand, or a cache), `items_changed(0, old, new)` on reset | reset ≤ 50 ms, scrolling smooth, memory sane, on this machine and on a ThinkPad X220-class machine (the author has one). Compare with `Gio.ListStore` of 70k items |
| S2 | Sorting by **our own** code with the header's sort indicator: column sorters as UI state only (`Gtk.CustomSorter` never asked to compare, or `ColumnView.sort_by_column` + listening to `ColumnView.get_sorter()` "changed"), no `Gtk.SortListModel` | header clicks re-sort through `PackageList`, the indicator follows, "ranked" shows no indicator |
| S3 | Row tint per mark (`ColumnView.set_row_factory`, CSS classes on `Gtk.ColumnViewRow`), hover highlight of the whole row (check whether GTK's own row hover already covers it), per-cell tooltips | looks like the Qt list in both themes |
| S4 | Status-cell click → action menu (`Gtk.GestureClick` in the cell, `Gtk.PopoverMenu` pointing at the cell); right-click anywhere on a row → package menu; double-click → `toggle_likely` | as in Qt, incl. multi-selection kept on right-click |
| S5 | Sidebar with an expandable tree (Environments) and a flat list in one widget | one implementation for all views |
| S6 | Dependencies tab of `kernel-core` (16k provides, cut to 1000 per section) as labels with links | builds in < 100 ms, no freeze |
| S7 | Painted icons (§7.3) sharp at 100/125/150/200 %, light and dark | matches the Qt icons side by side |
| S8 | Tests without a display: GTK 4 has no offscreen backend like Qt's. Try `xvfb-run` (X11 backend), `weston --backend=headless`/`mutter --headless` (Wayland), and `GDK_BACKEND=broadway`. Choose what works in COPR's `mock` %check | a GTK smoke test runs in `scripts/rpm_check.sh`'s container |
| S9 | Single instance with `Adw.Application(application_id=APP_ID)` **and** the existing `Activate(view, token)` method at path `/` (the tray calls it, `kram/instance.py`), plus focus with the token (`Gtk.Window.set_startup_id`) | the tray click focuses an open GTK Kram on Wayland (GNOME and Plasma) |
| S10 | The package split (§10): `kram` → `kram-qt` on `dnf upgrade`, never `kram-gtk`; tray units stay enabled; `dnf swap` both ways | decides the package names (D9). Can be done any time before the GTK release; earlier is better |

### 7.2 Module map Qt → GTK

| Qt module | GTK module | Notes |
|---|---|---|
| `ui/qt_loop.py` | `gtk/loop.py` | `post = lambda fn: GLib.idle_add(lambda: (fn(), GLib.SOURCE_REMOVE)[1])`, thread-safe as GLib is; at priority `GLib.PRIORITY_DEFAULT` so results keep their order |
| `ui/single_instance.py` | `gtk/app.py` | `Adw.Application`, flags `HANDLES_COMMAND_LINE` (for `--upgradable`) and `HANDLES_OPEN` (`kram file.rpm`); export the `Activate` interface at `/` in `do_dbus_register` (introspection XML from `kram/instance.py`); `hand_over` becomes GApplication's own remote activation |
| `ui/theme.py` | — | not needed |
| `ui/main_window.py` | `gtk/window.py` | a view of `app.Browser` |
| `ui/actions.py`, `ui/toolbar.py` | `gtk/actions.py` | `Gio.SimpleAction`s (stateful for checkables) from `ActionDef`s, `Gio.Menu`s from the menu structures; no toolbar styles |
| `ui/package_model.py`, `ui/package_view.py` | `gtk/package_list.py` | ListModel adapter over `PackageList` (S1), ColumnView, factories, header menu (`Gtk.ColumnViewColumn.set_header_menu`) to show/hide hideable columns, column state saved in `gtk/columns` |
| `ui/sidebar.py`, `ui/group_icons.py` | `gtk/sidebar.py` | view over `SidebarModel` + the ToggleGroup |
| `ui/search_bar.py` | `gtk/search.py` | DropDown + SearchEntry over `SearchController` (the entry's own `search-delay` stays 0: the controller debounces) |
| `ui/status_bar.py` | `gtk/status_bar.py` | |
| `ui/details.py`, `ui/file_list.py` | `gtk/details.py`, `gtk/files.py`, `gtk/doc_view.py` | |
| `ui/icons.py` | `gtk/icons.py` | §7.3 |
| `ui/links.py`, `ui/files.py` | `gtk/ui_port.py` | `Gtk.UriLauncher` (web links, after the scheme check), `Gtk.FileLauncher.open_containing_folder` (it uses FileManager1 itself), clipboard via `Gdk.Display.get_clipboard()` |
| `ui/markings_file.py` file dialogs | `gtk/ui_port.py` | `Gtk.FileDialog` (async, portal-aware), filters as `Gtk.FileFilter` |
| message boxes | `gtk/ui_port.py` | `Adw.AlertDialog` |
| each dialog | `gtk/dialogs/<name>.py` | views over the `app/*` state; build the simple ones first (What's New, Notifications, Cleanup), then Repositories, COPR, Custom Filters, History, Install, Upgrade, Apply + Progress last |
| drop of an .rpm | `gtk/window.py` | `Gtk.DropTarget` for `Gdk.FileList`, one local `.rpm`, deferred with `GLib.idle_add` as in Qt |
| `__main__.install_file` | `gtk/app.py` | `kram file.rpm` without the main window: the install dialog as the only window |

### 7.3 Icons in GTK

Draw `IconRef`s with cairo through a `Gdk.Paintable` (or `Gtk.Snapshot.append_cairo` in a small widget) in the
16×16 grid of `ui/icons.py`, with the same shapes and colours. Port each drawing function (`_box` with its pixel
snapping, `_arrow_up`, `_padlock`, `_hammer`, `_check`, the origin badges, the advisory dot, held ring and blocked
cross) and compare them side by side with the Qt icons (S7). The Noto Sans bold glyph text becomes Pango or cairo
text. Group icons and theme icons: `Gtk.Image.new_from_icon_name` with the `-symbolic` variant where Adwaita has one,
falling back to the names `app/icons.py` lists.

### 7.4 Order of work

All of phase 2 happens on one long-lived branch (`gtk`), branched from `main` after the phase 1 release and merged
from `main` regularly so it does not drift. Nothing of it is released until the GTK front end does everything the
Qt one does (D13). Parity is judged with a checklist made at the start of phase 2 from the Qt menus, dialogs and
`docs/guide/`, each item ticked when it works in GTK; it lives in §14.

1. S1–S10, results recorded. Stop and discuss if S1 or S8 fail.
2. Skeleton: `kram/gtk/app.py`, loop, window with header bar, panes, ToggleGroup, status bar; menu + actions + prefs
   (§4.1a); the entry point (§9). Catalog loads, list shows, sorting and filtering work.
3. Search, sidebar views, details (all tabs), navigation, context menus, shortcuts, settings.
4. Marking, Apply → review → progress → reload; markings files, CSV export, version lock.
5. Dialogs in the order of §7.2. History and undo.
6. Single instance + tray click, `kram file.rpm`, drop.
7. Polish: both themes, scaling, keyboard-only use, translations complete, screenshots.
8. The package split (§10, with S10's answer), README (installing `kram-gtk`, `dnf swap`), metainfo, then the
   release of GTK and the split together.

Every step ends with tests green in both front ends and a manual run on GNOME (a VM is fine) and Plasma.

---

## 8. Testing

- **Toolkit-free tests** for everything in `kram/app` and `kram/core`: plain pytest, `FakeScheduler`, a fake `Ui`
  recording calls and answering questions, `DnfWorker` with a synchronous `post`. Most of today's
  `tests/test_main_window.py` should become `tests/test_browser.py` against `Browser` with fakes; keep the Qt-specific
  rest (widget looks, row height, header state, deletion of dialogs) as Qt tests.
- **Qt tests**: as today, `QT_QPA_PLATFORM=offscreen`, `pytest.importorskip("PySide6.QtWidgets")`.
- **GTK tests**: `pytest.importorskip("gi")` + Gtk 4 / Adw 1 typelibs present + a display (S8); otherwise skipped.
  Smoke tests: every GTK module imports, the window builds with a fake catalog, each dialog opens and closes,
  icons render.
- `scripts/rpm_check.sh`: install each front-end package in the container and run its tests; check that the GTK
  package pulls in no Qt and the Qt package pulls in no GTK 4 (`rpm -q --requires`, `dnf repoquery --requires
  --resolve`).
- Speed: spike S1 measures the GTK list with a throwaway script (`scripts/perf_search.py` was removed on 2026-11-21;
  git history has it).

---

## 9. Entry points (no run-time choice, D8)

The front ends conflict and only one is installed, so nothing chooses between them.

- `pyproject.toml` cannot install two different `kram` scripts from one project, so the scripts are not generated from
  `[project.gui-scripts]` any more: the spec installs `/usr/bin/kram` per front-end subpackage, a three-line Python
  launcher (`from kram.qt.__main__ import main` / `from kram.gtk.__main__ import main`, `sys.exit(main())`). Keep
  `[project.gui-scripts]` out of the wheel, or point it at the Qt one only for `pip install -e .` development;
  decide while doing it and write down why.
- A source checkout runs either with `python3 -m kram.qt` or `python3 -m kram.gtk`.
- `kram file.rpm`, `kram --upgradable` and the tray's `Activate(view, token)` behave the same in both. The tray
  (`kram/notifier`) does not change: it starts `kram --upgradable` or calls `Activate`, whichever front end owns the
  bus name.

---

## 10. Packaging (D8, D9, D13)

The split ships together with the first GTK release (D13): until then `kram` stays one package, as today. One spec
(`packaging/kram.spec`), one SRPM, subpackages.

- **`kram-common`**: `kram/core`, `kram/app`, `kram/helper`, `kram/ipc`, `kram/notifier`, `kram/instance.py`,
  `kram/i18n.py`, `kram/__init__.py`, translations (`%find_lang`), `/usr/libexec/kram-helper`, the polkit policy,
  the systemd user units **and their scriptlets**, the tray icons, `/var/cache/kram`, metainfo, the app icon, the
  desktop files (one `.desktop` for both: `Exec=kram %f`; the Xfce settings entry). Requires: python3-libdnf5,
  python3-rpm, polkit, dnf5-plugins, hicolor-icon-theme, python3-gobject-base (tray), and a front end:
  `Requires: (kram-qt or kram-gtk)`, so that `dnf install kram-common` alone is not a broken install.
- **`kram-qt`**: `kram/qt`, `/usr/bin/kram` (Qt launcher). Requires kram-common = %{version}-%{release},
  python3-pyside6; Recommends qt6-qttranslations. `Conflicts: kram-gtk`. **`Obsoletes: kram < <split version>`,
  `Provides: kram = %{version}-%{release}`**: existing users are moved to it by `dnf upgrade`, and `dnf install kram`
  keeps working.
- **`kram-gtk`**: `kram/gtk`, `/usr/bin/kram` (GTK launcher). Requires kram-common = %{version}-%{release},
  python3-gobject (not -base: cairo), gtk4, libadwaita >= 1.7 (`Adw.ToggleGroup`; check every COPR chroot).
  `Conflicts: kram-qt`. **No `Obsoletes` and no `Provides: kram`**: only one package may obsolete `kram`, and a second
  provider of `kram` would make `dnf install kram` ambiguous. Switching: `dnf swap kram-qt kram-gtk` (README).

**Spike S10 decides the names (D9)**, in a Fedora container with `scripts/rpm_check.sh`'s setup:

1. Install the last single-package `kram` from a local repo; as a user, enable the tray checker
   (`systemctl --user enable --now kram-update-check.timer kram-update-check.path`) and note what is enabled.
2. Add the split packages to the repo; run `dnf upgrade`. Expected: `kram` erased, `kram-qt` + `kram-common`
   installed, `kram-gtk` not installed. Run it several times from scratch, and also `dnf distro-sync` and
   `dnf install kram` on a clean system.
3. Check the tray units are still enabled for that user. **Known risk**: on the obsoleted `kram`, rpm runs its
   `%preun` with `$1 == 0`, as on removal, and `%systemd_user_preun` disables the units for every user. If they end up
   disabled: fix it in `kram-common` (e.g. remember the enabled state in `%pretrans`/`%pre` and restore it in
   `%posttrans`, or move the unit scriptlets so that the erase of the old package does not disable them). Prove the
   fix in the same container.
4. `dnf swap kram-qt kram-gtk` and back: both work, nothing of the other toolkit stays required.

If step 2 or 3 cannot be made reliable: name the packages **`kram` (Qt) + `kram-gtk` + `kram-common`** instead (no
`Obsoletes` needed, `kram` simply becomes the Qt front end), and record why in §14.

`%check` runs the toolkit-free tests plus the installed front end's (S8 for GTK). `.copr/Makefile` needs no change
(one SRPM). `scripts/rpm_check.sh` checks each front end in turn, and that `kram-gtk` pulls in no Qt and `kram-qt` no
GTK 4 (`dnf repoquery --requires --resolve`).

---

## 11. Translations

- Moving code keeps msgids, so catalogs stay complete.
- New GTK-only strings (e.g. "Show Menu Bar", toggle labels if they differ, alert response labels where Qt used its
  own standard buttons Yes/No/Cancel/OK/Close) must be added to `po/kram.pot` and translated in **all 12 catalogs**
  before the tests pass (`scripts/i18n.sh update`, then translate). Ukrainian is reviewed by the author; the other
  11 are a first pass, as today (`docs/TRANSLATING.md`).
- Qt's own standard-button translations come from `qtbase_*.qm`; GTK/libadwaita bring their own (`gtk40`,
  `libadwaita`). Kram's catalogs need the strings Qt took from qtbase only where GTK has no stock equivalent.

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Phase 1 changes Qt behaviour by accident | small steps, existing tests, new characterization tests *before* each move (HTML comparisons, menu walks, action-state tables), manual runs |
| Continuation-style rewrite of the apply flow breaks ordering guarantees (`_reviewing`, keys captured at request time) | port the existing tests first; add tests for each `ask` branch |
| GTK ColumnView too slow for 70k rows with Python items | S1 before anything else; fall back to batching and lighter items; worst case a `Gtk.ListView` with one row widget drawing all cells |
| Two front ends double every UI feature | phase 1 makes the views thin; new features land in `kram/app` first; a feature may ship in Qt first with an issue for GTK |
| `kram.conf` corrupted by two writers | §4.1: one store, file lock, atomic replace, round-trip tests with QSettings |
| GTK tests cannot run in COPR's build | S8; if nothing works, GTK widget tests run only locally and in `scripts/rpm_check.sh` with a nested compositor |
| libadwaita too old on a COPR chroot | check versions per chroot before packaging; build the GTK subpackage only where it fits |

---

## 13. Questions and answers

Answered by the author on 2026-11-21; the answers are decisions D8–D13 in §1.

- Q1 Package names → D9 (`kram-qt` + `kram-gtk` + `kram-common` if S10 shows that `dnf upgrade` moves `kram` to
  `kram-qt` reliably and keeps the tray on; otherwise `kram` + `kram-gtk` + `kram-common`). Both front ends installed
  side by side: no, they conflict (D8).
- Q2 Which desktops get GTK when both are installed → moot: they cannot both be installed, and each `/usr/bin/kram` is
  written for its toolkit (D8).
- Q3 Rename `kram/ui` → `kram/qt` → yes, at the end of phase 1 (D10, step P1.16).
- Q4 Which settings the GTK front end has → the preferences registry (D11, §4.1a): status-icon click and "Watch Fedora
  Releases" in both; toolbar style Qt-only; "Show Menu Bar" GTK-only; any new setting in both unless it says otherwise.
- Q5 Hamburger while the menu bar is shown → hidden (D12).
- Q6 Releases → phase 1 as one release (later: merged into `main`, shipped with the next release); GTK on a branch until full parity, released with the package split (D13).

New questions go here, with the date, until the author answers them.

---

## 14. Spike results

Done 2026-11-22 on branch `feature/gtk`, scripts in `scripts/spikes/` (`common.py` loads a pickled snapshot from
`KRAM_SPIKE_SNAPSHOT`, else the real catalog read-only, else made-up rows). Machine: Intel Core Ultra 5 125U, 30 GB,
Fedora 45, KDE Plasma (Wayland), GTK 4.24.1, libadwaita 1.10.0, PyGObject 3.58.1, Python 3.15.2; the real catalog
had 68,290 rows. Fedora 44 has GTK 4.22.5 and libadwaita 1.9.4 (`Adw.ToggleGroup` needs 1.7).

| Spike | Result | Decision |
|---|---|---|
| S1 | A Python `Gio.ListModel` making items on demand: **~300 ms per reset**: GTK calls `get_item` for every added item of an `items_changed` (68,495 calls into Python), to find widgets it can keep. A `Gio.ListStore` refilled with new items: also ~300 ms (the Python items), and GTK tears down every cell widget when it finds none of the old items. **Fixed position items** in a `Gio.ListStore` (items stand for positions, not packages; a reset only adds or removes items at the end; the bound cells are drawn again from `PackageList`): **1–11 ms** for the store change, 16–50 ms per reset with PackageList's own sort. Re-sort by summary ~55–70 ms (the Python sort is ~45 ms of it, the same in Qt). Scrolling: 3 rows a frame, 0 frames over 33 ms; half a page a frame (a flung scrollbar), median 16.7 ms, p95 ~33 ms. Memory ~270 MB RSS with the catalog (160 MB of it the catalog). One case stays slow: from a list shorter than the screen to all rows **~90–140 ms**: GTK drops the widgets of the missing rows and builds ~1,600 cell widgets again (~70 ms of it GTK's own: a `Gtk.BuilderListItemFactory` with no Python costs the same). | `kram/gtk/package_list.py` uses fixed position items. To do: the same run on the X220 (`python3 scripts/spikes/s1_column_view.py positions`) |
| S2 | Each column gets a `Gtk.CustomSorter` with no function, never asked to compare (no `Gtk.SortListModel`); the view's `ColumnViewSorter` "changed" → `PackageList.sort`. A header click keeps the old column as a secondary sort that still shows its arrow, so the view re-sets the indicator to the one column; `sort_by_column(None)` clears it for ranked results. | as described |
| S3 | Tint: a CSS class per action on each cell's own box, which takes the cell's padding (cells get `padding: 0`) so the tint fills the row without gaps, `background-image: image(rgba(…))` from `MARK_BACKGROUND`, so Adwaita's hover and selection colours still show through; the same translucent colours read well in both themes. `data-table` rows already have a hover highlight. Per-cell tooltips: `set_tooltip_text` at bind. First tried on the row widget (the cell's grandparent): changing its classes during a bind inside `items_changed` makes GTK abort (`gtk_accessible_update_state` criticals) when an empty, realized list fills. | as described; no dark variant of the colours needed |
| S4 | A `Gtk.GestureClick` per cell: status cell → menu at the cell; right click → keeps a multi-selection when the row is in it, else selects the row; double click → the view's `activate`. `Gtk.PopoverMenu` from a `Gio.Menu`. Wired and checked programmatically; **to check by hand** (`s2_s4_list.py OUT --stay`): clicks, right-click on a multi-selection. | |
| S5 | One `Gtk.ListView` (`navigation-sidebar`) over a `Gtk.TreeListModel` for every view: flat views are entries without children, Origin's repositories are children always unfolded with no arrow (`hide-expander`), Environments fold. Vertical homogeneous `Adw.ToggleGroup` below; all six icons exist in Adwaita. | `kram/gtk/sidebar.py` |
| S6 | `kernel-core`: 16,083 provides, 1,000 shown. One wrapping label per section: **~2 s** to the first frame. 50-line labels without wrapping: **~60 ms**; the doc is built in 3 ms. Section lines do not wrap (a long dependency scrolls sideways). | `kram/gtk/doc_view.py` |
| S7 | A cairo node per icon could not be snapped to the screen's pixels (its CTM is not the screen's grid). Instead each icon is drawn once per screen scale into a texture of exactly that many pixels and placed with the NEAREST filter, as Qt caches pixmaps; the window tells `kram.gtk.icons.set_scale`. Side by side with Qt at 100/125/150/200 %, light and dark: the same pixels, crisp 1 px borders (`s7_icons.py`). Glyphs need grey antialiasing (subpixel fringes otherwise). | `kram/gtk/icons.py`. To do: a look at a real 125 %/150 % screen |
| S8 | In a Fedora 44 container: `GDK_BACKEND=broadway` with `gtk4-broadwayd` (in `gtk4` itself, no GL) works and is the cleanest; `xvfb-run` and `weston --backend=headless` work too (software Vulkan, noisy warnings); `mutter --headless` needs a session bus. | GTK tests under broadway; `%check` in mock still to try with the packaging (§10) |
| S9 | `Adw.Application(application_id=APP_ID, HANDLES_COMMAND_LINE)`; `Activate(view, token)` exported at `/` from `do_dbus_register`. A second `kram --upgradable` hands its command line to the first (GApplication's own remote activation, `XDG_ACTIVATION_TOKEN` arrives as the platform data's `activation-token`) and exits 0; a `gdbus` call of Activate reaches the window, which calls `set_startup_id(token)` before `present()`. **To check by hand**: a real tray click focusing the window on Plasma and GNOME (`s9_instance.py --id io.github.elmodos.Kram` with no Kram running). | `kram/gtk/app.py` |


---

## 15. Phase 1 progress

Done on `gtk-prep` (2026-11-21), each step with `ruff` and the whole suite green in the `kram-test:44` container, and
a run of the real window (catalog load, search, marking, every sidebar view, settings saved on close) in a container
with a real dnf cache:

| Step | What exists now | Differences from the plan |
|---|---|---|
| P1.0 | `kram/app/__init__.py`, `tests/test_toolkit_free.py` | also blocks `shiboken6` |
| P1.1 | `kram/core/settings.py` (`store`), `tests/test_settings.py`, fixture `tests/data/kram-0.11.3.conf` (a real file, values replaced) | keys the store does not change are written back byte for byte (raw value text), so `@ByteArray` keys survive by construction; the lock is Qt's own `kram.conf.lock` (QLockFile protocol, flock held), so it also excludes a QSettings writer in another process; `tests/conftest.py` points `XDG_CONFIG_HOME` at a temporary directory for every test |
| P1.2 | `kram/app/scheduler.py` (`Scheduler`, `Timer`, `FakeScheduler`), `kram/ui/qt_loop.QtScheduler(parent)` | the Qt scheduler takes a parent: its timers die with the widget, so nothing fires into a deleted widget |
| P1.3 | `kram/app/columns.py`, `kram/app/icons.py`; `kram/ui/icons.icon(ref)` draws any `IconRef` | cells are asked per aspect (`cell_text`, `cell_tooltip`, `cell_icon`, `cell_style`) because Qt asks per role; `cell()` combines them. IconRef kinds added: `("all",)`, `("user",)`, `("marked",)` |
| P1.4 | `kram/app/package_list.py` (`PackageList`); `PackageTableModel` forwards its signals | signals `about_to_reset`/`reset`, `about_to_sort`/`sorted(moved)`, `rows_changed(positions)`. measured with `scripts/perf_search.py` (broken on `main`, fixed for this): no slowdown; the script was then removed at the author's request |
| P1.5 | `kram/app/actions.py` (`ActionDef`s, menu structures, `action_state`, `downgrade_items`), `kram/app/preferences.py` | `tests/test_actions.py` compares the Qt menus with ones recorded from 0.11.3 (`tests/data/qt_menus_0.11.3.json`). Find and Quit keep Qt's platform standard keys. "Show Menu Bar" (gtk only) is translated in all 12 catalogs (first pass, uk to review). The Settings menu entries and the Toolbar submenu come from the registry; `ReleaseWatcher` reads the watch setting from it |
| P1.6 | `kram/app/ports.py` (`Ui`, `Question`, `Button`, `RecordingUi`, `is_web_link`, `parse_filters`), `kram/ui/qt_ui.py` (`QtUi`) | file filters stay in Qt's syntax (keeps the msgids); `parse_filters` turns them into pairs for GTK |
| P1.7 | `kram/app/marking.py` (`Marker`, `group_menu`), `kram/app/markings.py` | `kram/ui/marking.py` and `kram/ui/markings_file.py` are gone; dynamic menus are `DynamicItem` lists, Qt fills them with `kram.ui.actions.fill_dynamic` |
| P1.8 | `kram/app/search.py` (`SearchController`); `SearchBar` is the two widgets | |
| P1.9 | `kram/app/sidebar.py` (`SidebarModel`, `Listing`); `Sidebar` draws listings | |
| P1.10 | `kram/app/doc.py`, `kram/ui/doc_html.py`, `kram/app/details.py` (builders), `kram/app/empty_list.py`, `kram/app/whats_new.py` | `tests/test_doc.py` compares the HTML byte for byte with that of 0.11.3 (`tests/data/html_0.11.3.json`, inputs `tests/doc_fixtures.py`). The install dialog's tabs are left for P1.14, with the rest of that dialog |
| P1.11 | `DetailsLoader`, `DetailsSink`, `TabChoice` in `kram/app/details.py` | |
| P1.12 | `kram/app/browser.py` (`Browser`, `BrowserView`, `ReposChoice`), `kram/app/status.py`; `MainWindow` is a view of `Browser` (~520 lines, from ~1120) | the window's dialogs are `BrowserView` methods (`review_changes`, `run_helper`, `show_repos`) rather than `Ui` methods: they are the window's. COPR, Cleanup, History, Upgrade, Notifications, Install and About are still opened by the window, calling `Browser` for the flows around them (undo, helper runs, reload); their own logic is P1.14. Quitting is `Browser.can_close(done)`. `tests/test_browser.py` covers the flows toolkit-free (each question of Apply, quit, undo, repositories); `tests/test_main_window.py` still drives the window, through `window.browser` for the state that moved |
| P1.13 | `kram/core/net.py` (`fetch`, `fetch_json`, `Request`, `NetError`), `kram/core/proc.py` (`run`, `Process`, `spawn_detached`), the `Bus` port (`kram/app/ports.py`, `FakeBus`; Qt: `kram.ui.files.QtBus`); `tests/test_net_proc.py` (a local HTTP server, real child processes) | a daemon thread per request instead of a thread pool (a pool's threads are joined at exit, so a slow Copr search would hold up quitting); cancelling is a handle (`Request.cancel()`, `Process.kill()`) rather than a `threading.Event` argument, and a cancelled request's answer is dropped on the main thread even when it was already posted. The Copr search reads raw bytes (`fetch`) so a non-JSON answer keeps its translated message; it now sends Kram's User-Agent like the other requests. Closing the notifier dialog kills a waiting `systemctl`, as QProcess's destructor did. QtDBus stays in `files.py` (FileManager1, `QtBus`) and `single_instance.py`. Checked live in the container: Bodhi, Copr chroots, Copr search, `rpm -V` through Qt's `post`; by the author on their machine: enabling `dnf-makecache.timer` (polkit asks, the dialog follows). Not checked yet: opening Discover from the Fedora N dialog (needs an older release) |
| P1.14 | `kram/app/release_watch.py`, `custom_filters.py`, `progress.py`, `apply_review.py`, `history.py`, `copr.py`, `upgrade.py`, `notifier.py`, `repos.py`, `cache.py`, `filters_edit.py`, `install.py`, one commit each; `ports.view_ref` | each dialog's logic object talks to its dialog through a small view protocol (`ProgressView`, `ApplyReviewView`, `HistoryView`, …) and holds it weakly (`ports.view_ref`), and `QtUi` holds its parent weakly: dialog ↔ logic was a reference cycle, and PySide6 crashed when the garbage collector freed one (reproduced in `tests/test_distro.py`). Questions go through the `Ui` port, so the tests that faked `QMessageBox` use `RecordingUi`. `doc.filled()` turns a translated template into spans (a bold size where the translation puts it). The state marks OK / WARN / ERROR / INFO moved to `kram/app/icons.py` with `STATE_ICONS`. `Browser.clean_cache` and the cleanup dialog's helper runs are continuation style (`Browser.run_helper`); `MainWindow._helper_result` is gone. The install dialog's logic is `app/install.py` (`Install`, `InstallView`): the header's lines are `Note`s (a state kind and spans), its tabs are docs (the doc model gained `Colored` and `Section.marked` for the requirement marks), and the transaction runs through `InstallView.run_transaction(request, title, done)`; `tests/test_install_flow.py` drives it toolkit-free. Checked in a container over a real 70k-package catalog: every moved dialog opens and fills (cleanup, history, repositories, COPR, notifications, filters, a real Apply review), and the install dialog shows the same text as before for an installable and a blocked file |
| P1.15 | dead code removed (`ChangesTree.set_basearch`, `status_filter_icon`, the upgrade dialog's test wrappers, three constants already unused on `main`); module docstrings point to their logic module; `docs/PLAN.md` §3 shows `kram/app` | — |
| P1.16 | `kram/qt` (was `kram/ui`), `kram/qt/__main__.py` (was `kram/__main__.py`), the `kram` command is `kram.qt.__main__:main`; `po/kram.pot` regenerated (references only, the msgids are the same set) | `python3 -m kram` is gone: a source checkout runs `python3 -m kram.qt` (CONTRIBUTING, TRANSLATING, the tray's fallback). The `.po` files keep the old references until the next `scripts/i18n.sh update`. `scripts/rpm_check.sh` also checks the installed command's entry point |
| P1.17 | squash-merged into `main` (2026-11-21), no release of its own | the plan had a release; the author chose to ship phase 1 with the next release that has a user-visible change (D13) |

**Phase 1 against this plan, in short** (for whoever starts phase 2):

- Everything §4 planned to move is in `kram/app`, and `kram/ui` only draws and forwards. `kram/ui` ended at ~5.1k
  lines (from ~8.1k), not at half: the widgets themselves (the package view's column fitting, the file tree, the
  painted icons, the dialogs' layouts) are most of what is left, and GTK writes its own of each anyway. `kram/app`
  is ~6.2k lines, `kram/core` ~4.7k.
- Not in the plan, needed on the way: `core/net.py` and `core/proc.py` take cancel handles, not events (P1.13);
  every dialog's logic holds its view weakly (`ports.view_ref`), because PySide6 crashes when the garbage collector
  frees a dialog ↔ logic cycle (P1.14); the doc model gained `filled()`, `Colored` and `Section.marked` (P1.14).
- Different from the plan: the window's own dialogs are `BrowserView` methods, not `Ui` methods (P1.12); questions
  are continuation style everywhere, Qt answers them before `exec()` returns, GTK will answer them later.
- The Qt behaviour is unchanged as far as the tests and the container runs can tell (the menus, the detail HTML and
  the install dialog's text were compared with 0.11.3 or with the code before the move); the author's own run of
  the branch was the last check before the merge.

---

## 16. Phase 2 progress

On `feature/gtk`. Run from a checkout with `python3 -m kram.gtk`. GTK tests: `tests/test_gtk.py`, skipped without
GTK 4 and libadwaita ≥ 1.7; without a display the module starts `gtk4-broadwayd` for itself (S8). The local
`kram-test:44` image has `gtk4 libadwaita` since 2026-11-22 (a layer over the old one, kept as
`kram-test:44-pre-gtk`), so a plain `python3 -m pytest -q` there runs them.

**Skeleton (§7.4 step 2), 2026-11-22.** `kram/gtk`: `app.py` (Adw.Application, single instance and the tray's
Activate, S9), `loop.py` (`post`, `GtkScheduler`), `ui_port.py` (`GtkUi`: Adw.AlertDialog, Gtk.FileDialog,
launchers, clipboard; `GioBus`), `actions.py` (Gio actions, accelerators, the table's ShortcutController, Gio
menus from `kram.app.actions`, the preference actions from the registry), `window.py` (the BrowserView: header
bar, optional menu bar (D6/D12), panes, empty-list overlay, status bar, context menus), `package_list.py` (S1–S4),
`sidebar.py` (S5), `doc_view.py` (S6), `icons.py` (S7), `details.py` (Adw.ViewSwitcher tabs), `search.py`,
`status_bar.py`. The catalog loads, the list shows, sorting, the sidebar views, search, details and marking work.

**Dialogs (§7.4 steps 3–6), 2026-11-22.** `kram/gtk/dialogs/`: `common.py` (trees and tables over
`Gtk.ColumnView`, read-only text, the dialog frame), `apply.py` (Apply review), `progress.py` (the helper's
progress: no closing mid-transaction), `notifier.py` and `cache.py` (preferences dialogs; Cleanup's Compare
view), `repos.py`, `copr.py`, `filters.py` (Custom Filters), `history.py` (a window of its own, not modal),
`install.py` (the installer as a dialog, or as the only window of `kram file.rpm`), `upgrade.py` (the "Fedora N"
button's check). Also: What's New as libadwaita's own page of the About dialog (`release_notes`), the Files tab
(`gtk/files.py`: tree or list, filter, Copy Path, Show in File Manager), the Versions table, the column titles'
menu to show or hide columns and the saved column state (`gtk/columns`), the drop of an .rpm, markings files and
the CSV export (the existing `Browser` flows). Every action of the menus now does what it does in Qt; the "not
yet" placeholder is gone.

How it was checked: `tests/test_gtk.py` (one or more tests per dialog, over fakes), and a run over the real
catalog on the author's machine (Fedora 45, KDE) with a throwaway configuration (`XDG_CONFIG_HOME`), screenshots
of every dialog but Install and Fedora N; Apply was opened to the review only. **Not checked yet**: a real
transaction through the progress dialog (only with a fake helper), the installer with a real .rpm file, the
Fedora N dialog with a real new release, GNOME itself, keyboard-only use, HiDPI.

Things noticed on the way:

- `Adw.ToolbarView` is final (no subclass): `InstallPage` is a box that holds one.
- A `Gio.ListStore.splice` that puts the same object back does not bind its row again: the history puts a new
  item in to show a row's counts.
- A view's "current" setter must tell the logic as a click would (`History` expects that from Qt's
  `setCurrentItem`); only a refill or a filter change of the same row is silent.
- A hidden `Adw.Window` keeps the application running: the main window destroys the history window on close.
- `kram file.rpm` runs a `NON_UNIQUE` application of its own, as Qt does, instead of going to the open Kram.
- The test run ends with a GLib-CRITICAL `g_main_context_pop_thread_default` at interpreter exit (PyGObject's
  asyncio policy); it was there before the dialogs and does not fail anything.

Still to do (§7.4 steps 7–8): both themes and GNOME itself, scaling, keyboard-only use, translations, screenshots;
the package split and README. Things to settle:

- New GTK-only strings: none so far beyond GTK's own ("gtk40": alert and dialog buttons); every label of the
  dialogs is an msgid the Qt front end already has. Every new msgid must go into all 12 catalogs before the tests pass
  (§11), so they will be added in batches.
- Adwaita has no funnel icon: while the search filters, the field gets an accent outline and a tooltip instead.
- The advisories tab shows libadwaita's attention dot, not the advisory's colour dot (view switcher pages take
  theme icon names only).
- Painted icons in menus (Why It Cannot Be Upgraded's cross, the dynamic items' icons): GTK popover menus show no
  icons for ordinary items; left out.
