# A terminal front end for Kram (`kram-tui`) — concept

Status: **concept and spikes** (2026-11-23) on branch `feature/tui`. The binding description for implementation
is `docs/TUI_SPEC.md`; this document keeps the reasons and the spike results. Two throwaway spikes show every layout and
dialog described here over the real catalog (70,235 rows of Fedora 44): `scripts/spikes/t1_tui.py` (the window)
and `scripts/spikes/t2_dialogs.py` (the dialogs that need root). Nothing of `kram/tui` exists yet; nothing is
released.

This document is written for whoever implements it, possibly without the conversation it came from. Every claim
about the code base was true at commit `a9fa6fe` (after release 0.13.0). Check it against the code before you rely
on it.

---

## 1. Why, and what was decided

Kram has a Qt and a GTK front end over one toolkit-free layer (`kram/core`, `kram/app`, `kram/ipc`; see
`docs/GTK_FRONTEND.md`). A third front end for the terminal serves servers, SSH sessions and people who live in a
terminal, the way aptitude sits next to Synaptic on Debian.

| # | Decision | Date |
|---|---|---|
| T1 | **Textual** (Python, `python3-textual` in Fedora). It is a thin layer over `kram/app` like `kram/gtk`; urwid would need its own layout and overlay code, prompt_toolkit has no tables or panels, ratatui would be a second language next to the Python core. | 2026-11-23 |
| T2 | **Textual 4.0 is the floor**: Fedora 43 and 44 ship 4.0.0, Fedora 45 ships 8.1.1. Everything is written for 4.0 and checked on both (the spikes' screenshots are the same on both). | 2026-11-23 |
| T3 | **The Synaptic layout** (variant A of the sketches): sidebar on the left, package list, details below, as in the GUIs. | 2026-11-23 |
| T4 | **The package list draws only the lines on screen** (a `ScrollView` with `render_line` over `PackageList`). Textual's `DataTable` takes 4.4–5.1 s to fill with 70k rows. | 2026-11-23 |
| T5 | **The panels adapt to the terminal**: from 100 columns they are pinned beside and under the list; below that they slide over the list, one at a time (§3). | 2026-11-23 |
| T6 | **`g` and `d` toggle the sidebar and the details by focus**: not focused → show and focus; focused → hide and go back to the list (§3.2). | 2026-11-23 |
| T7 | **The focused panel has the accent border**; the others are grey. | 2026-11-23 |
| T8 | **Views and tabs**: every tab shown when they fit, else the current one between arrows; `[` and `]` step, a letter opens the list (`v` views, `t` tabs) (§5). | 2026-11-23 |
| T9 | **Key hints are drawn as keys**: lower case (as typed), in the footer's key colour, each followed by a word: `[ prev  ] next  v all`. Bare `[ ]` read as an empty checkbox. | 2026-11-23 |
| T10 | **Classic arrows** `← → ↑ ↓`, no triangles (`◂ ▸ ▾`). Status glyphs in the list (`▲ ■ □`) are marks, not arrows; still open whether they become ASCII (§13). | 2026-11-23 |
| T11 | **Centre scrolling as in mc**, on by default, a setting: the cursor stays mid-list and the list moves under it. | 2026-11-23 |
| T12 | **Search is a modal popup at the top of the screen** (`/`), the menu a modal popup in the middle (`m` or `F9`, as in mc). No permanent menu bar line. | 2026-11-23 |
| T13 | **No UI library of our own for modality**: Textual's screen stack and focus chain are the responder chain; one rule on top decides which keys belong to the window (§7). | 2026-11-23 |
| T14 | **Buttons are one line high**, our own widget. Textual's `Button` is three lines high: ugly in a terminal, and it does not fit a narrow one. Never use it. | 2026-11-23 |
| T15 | **Root in a terminal has three paths**: Kram runs as root; a desktop polkit agent; polkit's text agent on the terminal while Kram steps aside (§8). | 2026-11-23 |
| T16 | **No colour is hard-coded.** Every colour is a role (§9a) taken from the scheme. The default scheme is the terminal's own 16 colours with its own background and text, so the terminal's light or dark mode shows at once, with no restart; 16-colour schemes of our own and Textual's high-colour themes are a choice in the menu, applied at once. | 2026-11-23 |
| T17 | **Progress bars are as wide as their dialog.** | 2026-11-23 |
| T18 | **Box drawing with square corners**: a panel has a single line (`┌─┐`), a modal window a double one (`╔═╗`). No rounded corners. | 2026-11-24 |
| T19 | **In 16 colours nothing is blended**: modal screens are `transparent` (the window stays in sight under them; `$background 0%` stays opaque in ANSI mode), the footer, text fields and checkboxes take plain theme colours. Inactive frames in high colour are the text colour at 30%, as the theme's own border colour vanishes on dark themes. | 2026-11-24 |
| T20 | **The Summary column takes the room left** (at least 20), so a wide terminal does not scroll sideways for it. Scrollbars and dialog table headers are quiet. | 2026-11-24 |
| T21 | **One checkbox look**, `[x] Label`, our own widget: Textual's `Checkbox` and `SelectionList` look different from each other and from the repositories table. | 2026-11-24 |

Non-goals: mouse-first use (the mouse works where Textual gives it for free, nothing is designed for it); a second
toolkit-free layer (the TUI uses `kram/app` as the GTK front end does); features the GUIs do not have.

---

## 2. The window

```
 Kram  Upgradable (13) · 3 marked                                     [ROOT when root]
╭ Status ───────────╮╭ Packages ──────────────────────────────────────────────────────╮
│ All        70,235 ││ S Package          Installed      Latest         Repository … │
│ Installed     569 ││ ▲ file-libs        5.46-10.fc44   5.48-2.fc44    updates      │
│ Upgradable     13 ││ ▲ libavcodec-free  8.1.3-2.fc44   8.1.3-3.fc44   updates      │
│ …                 │╰──────────────────────────────────── space mark  ← → scroll ─╯
│ ● Status          │╭ Details ───────────────────────────────────────────────────────╮
│   Origin          ││ 1 Description │ 2 General │ 3 Advisories │ 4 Dependencies │ … │
│   …               ││ file-libs 5.48-2.fc44                                           │
╰ [ prev ] next v all╯╰──────────────────────────────────── [ prev  ] next  t tabs ─╯
 space Mark  g Groups  d Details  / Search  m Menu  q Quit  f5 Reload  a Apply
```

- **Top line**: the shown filter or search and its count, the number of marks, and a `ROOT` badge when Kram runs as
  root ("changes need no password").
- **Footer**: Textual's `Footer`, the keys of the focused widget and its parents. Keys that do not apply now are
  left out (§7).
- **Panel borders** carry the panel's name in the top border and its own key hints in the bottom one.

## 3. Panels

### 3.1 Wide and narrow

| Terminal | Sidebar and details |
|---|---|
| ≥ 100 columns (`WIDE`) | Pinned: they take room from the list. The user can hide either; that is remembered (`pinned`). |
| ≥ 100 columns and ≥ 34 rows (`TALL`) | The sidebar also lists every view at its bottom, as the GUIs do (GTK D7). |
| < 100 columns | Hidden; `g`/`d` slide one over the list (`layer: overlay`, the sidebar `position: absolute` on the left, the details `dock: bottom`). The list does not shrink. |

The details slide-over is 11 lines, but at most 3/5 of the room, so that a few rows of the list stay in sight
(on 40×12 two rows stay).

### 3.2 `g` and `d`

- The panel is not focused: show it (pinned in a wide terminal, the one slide-over in a narrow one) and focus it.
- The panel is focused: hide it and focus the list. In a wide terminal that unpins it.
- `Esc` in a panel: focus the list. A pinned panel stays; a slide-over closes.
- The focus goes to the list in any way (Tab, a click, picking a filter): a slide-over closes.

### 3.3 Edge cases (each is a screenshot case of `t1_tui.py shots`)

1. A slide-over over a short list: the list cannot scroll, so the cursor would end up under the details. The list
   gets extra lines at its end while the slide-over is open (`bottom_inset`), and scrolls the cursor above it.
2. Only one slide-over at a time: `g` while the details slide over closes them.
3. Narrow → wide with a slide-over open: it becomes a pinned panel and keeps the focus. Wide → narrow: every panel
   hides but the focused one, which becomes the slide-over.
4. Tiny terminals (40×12): the details slide-over leaves two rows of the list.
5. A view with no entries (no searches, no custom filters) shows a hint instead of nothing:
   "No searches yet. Press / to search."
6. Long group names are cut with `…`; the count stays on the right.

## 4. The package list

- **Only the lines on screen are drawn**: `render_line(y)` reads `PackageList.row(scroll_y + y - 1)`; line 0 is the
  header. Cells come from `kram.app.columns.cell_text`, as in the GUIs. Headers are shorter than the GUIs'
  (`Installed`, `Latest`, `Size`).
- **Sideways scrolling** (`←`/`→`, `h`/`l`) when the columns do not fit. The status and name columns stay in place
  when they take at most half the width; otherwise the whole line scrolls.
- **The name column** is as wide as 95% of the shown names (12–48 characters), so that one 81-character name does
  not push every other column away.
- **Centre scrolling** (mc's option): the cursor stays mid-list; near either end the list stops and the cursor moves
  on. A setting (in the spike: Settings → "Centre the cursor when scrolling"), on by default.
- Every `scroll_to` of the list passes `force=True`: Textual refuses to scroll a widget that has no scrollbar yet,
  which is the case for a short list right after the details slide over it.

## 5. Sidebar views and detail tabs

### 5.1 Sidebar (Status, Origin, Groups, Environments, Search results, Custom filters)

- The view's name is the panel's title. `[` and `]` go to the previous and next view; `v` opens the list of views
  (a small modal list). A wide and tall terminal also lists them at the bottom with `●` at the current one.
- Changing the view does not filter the list; picking an entry (`Enter`) does, as in the GUIs. In a narrow
  terminal picking an entry also closes the slide-over.
- `←`/`→` are kept free on purpose: the Environments view needs them to fold and unfold (not in the spikes yet).
- Entries come from `kram.core.filters` (`status_filters`, `origin_filters`, …), as `SidebarModel` builds them.

### 5.2 Details (Description, General, Advisories, Dependencies, Files, Versions, Changelog)

- When all tabs fit: `1 Description │ 2 General │ 3 Advisories │ …`, the current one in reverse, Advisories in the
  warning colour. When they do not: `← Description → 1/7  ! advisories`.
- `[` and `]` step, `1`–`7` go to a tab, `t` opens the list of tabs.
- The Advisories tab comes and goes with the package; `kram.app.details.TabChoice` brings it back for the next
  package that has one when the user had picked it, as in the GUIs.

## 6. Search and menu

**Search (`/`)**: a modal popup at the top of the screen (a command palette). An input line; the five modes of
`kram.core.search` under it (`Tab`/`Shift+Tab`; when they do not fit, `← Name + summary → 2/5`); a live count for
the name modes (Provides and File ask dnf, so only on `Enter`); `↓` to the earlier searches. `Enter` searches:
results are ranked, and the sidebar switches to Search results with the search selected. `Esc` closes.

**Menu (`m`, `F9`)**: a modal popup in the middle: the menus of `kram.app.actions.menu_bar()` on the left, the chosen
menu's entries on the right, with their shortcuts; submenus open in place with a `← Back` line; preferences show a
real checkbox `[x]`. `←`/`→` move between the columns, `Enter` runs, `Esc` closes. The menu is the GUIs' menu: an
action added to `kram/app/actions.py` shows up here too.

## 7. Who gets a key (modality, "first responder")

Textual already has the pieces of a responder chain:

1. **Screens are a stack.** A `ModalScreen` (search, menu, every dialog) covers the window; the window under it gets
   no keys and no clicks.
2. **The focused widget is the first responder.** A key goes to the focused widget, then to its parents, the screen
   and the app; the first binding that matches wins (priority bindings are checked first).
3. **A text field takes printable keys itself**, before any binding of its parents.

One gap: the app is the parent of every screen, so the app's own bindings (`g`, `d`, `/`, `m`, `q`) still answer
under a modal screen. The rule that closes it, in one place (`KramTui.check_action`):

> The window's keys (`WINDOW_ACTIONS`) work only while no modal screen is up and no text field has the focus.

`check_action` returning `False` also takes them out of the footer. This is the scope `kram/app/actions.py`
already gives its actions (`scope="window"` / `"table"`), applied to the terminal: a front end-free rule, and no UI
library of our own (T13). Checked in the shots: in the search `g` is a letter and the panels do not move; under the
menu `g`, `d` and `/` do nothing.

Keys, by where they work:

| Where | Keys |
|---|---|
| Window (main screen, no text field focused) | `g` sidebar, `d` details, `/` search, `m`/`F9` menu, `F5`/`Ctrl+R` reload, `a` apply, `q` quit, `Esc` back to the list |
| List | `↑↓`/`jk`, `PgUp`/`PgDn`, `Home`/`End`, `←→`/`hl` sideways, `Space` mark |
| Sidebar | `[` `]` view, `v` views |
| Details | `[` `]` tab, `1`–`7`, `t` tabs |
| Any modal | `Esc` closes or cancels; `Tab` moves between fields and buttons; `Enter` presses the focused button |
| A dialog's main action | `Ctrl`+letter (priority bindings), so that it works from a text field too: `Ctrl+A` apply, `Ctrl+E` enable |

## 8. Root

The GUIs start the helper (`kram/helper/kram_helper.py`) with `pkexec` (`kram/ipc/client.py`), once per session;
polkit's message is Kram's own (`data/io.github.elmodos.Kram.policy`). In a terminal pkexec has a problem: when no
polkit agent is registered for the session, it falls back to a text agent on the controlling terminal and writes
its prompt straight over Textual's screen. Three paths:

| Kram runs | What happens |
|---|---|
| As root (`sudo kram-tui`, a root shell) | The helper starts without pkexec. The top line shows a `ROOT` badge: "changes need no password". |
| In a desktop session with a polkit agent | pkexec is started in a new session (`start_new_session=True`: no controlling terminal), so its prompt can only be the desktop's window. Kram's progress dialog says "Waiting for authentication… Your desktop asks for the password in its own window." |
| With no agent (SSH, a virtual console) | That pkexec fails at once ("No authentication agent found", exit 127). Kram says why in a dialog (Continue / Cancel), then steps aside with `App.suspend()`: the terminal is the shell's again, Kram prints one line of context, runs pkexec on the terminal, and polkit's text agent asks for the password. Then Kram comes back. |

The helper stays alive for the session after that, as in the GUIs, so the password is asked once.

**To verify in a spike (T3)** before building on it: that pkexec without a controlling terminal really fails fast
with no agent instead of hanging; that the desktop agent still shows its window then; that `App.suspend()` hands the
terminal back cleanly on both Textual versions; and what `sudo kram-tui` means for the user's settings (`$HOME` is
root's under `sudo -i`, the user's under plain `sudo`). `t2_dialogs.py` has `KRAM_SPIKE_PKEXEC=1` to run a real
`pkexec /usr/bin/true` on the third path.

## 9. Dialogs

All dialogs are modal screens with a rounded accent border, its title at the top and its key hints at the bottom,
one-line buttons on the right (T14), the default button focused. A button reads `< Apply >`, as in dialog(1) and
whiptail, and uses only what 16 colours have: focused in reverse, the default one bold, a dangerous one in the
error colour, a disabled one dim and skipped by `Tab`. They draw what the existing presenters of
`kram/app` say, through the same view protocols as the GUIs.

| Dialog | Presenter | In the terminal |
|---|---|---|
| Progress (reload, apply, COPR, repositories) | `kram.app.progress.Progress` → `ProgressView` | The stage line in bold, a download bar as wide as the dialog (T17), for a transaction a package bar, the last lines of the log. No Close button while it runs (`Esc stop` until the transaction starts); `Enter close` when done. |
| Apply changes | `kram.app.apply_review.ApplyReview` → `ApplyReviewView` | Summary line (counts, download, free space); the loud warning in red (`removal_warning`, e.g. essential packages); the changes by kind in their colours; recommended packages as a checkbox list ("untick to leave them out"); `Download only`; the `dnf5` command. Everything between the summary and the buttons scrolls as one: a list of its own got no lines at all in a narrow terminal. Narrow rows show only name, resulting version and size. `Ctrl+A` applies. |
| Repositories | `kram.app.repos.Repos` → `ReposView` | A filter line; the table with a real checkbox per repository (`Space`), changes not applied yet in bold with `*` and listed under the table; debug and source repositories hidden until `Ctrl+D`; buttons Packages, Mirrors…, Remove file…, Apply. Applying needs root (§8). Closing with changes not applied asks first (not in the spike). |
| COPR | `kram.app.copr.CoprProjects` → `CoprView` | The projects on this system (or "No COPR projects yet. Search for one below."), the search line, the results with "Builds for this system" (`✓ fedora-45-x86_64` in green, `✗ fedora-42-x86_64` in red: such a project cannot be enabled), Disable / Remove… / Enable (`Ctrl+E`). |

## 9a. Colours

**Roles, not colours.** One hidden widget (`Palette` in `t1_tui.py`) holds every colour of the TUI as a component
class per role: `muted`, `rule`, `key`, `current`, `header`, `cursor`, `cursor-blurred`, `upgradable`,
`installed`, `marked`, `info`, `danger`, `ok`, `badge`. Text drawn in Python asks `role(name)`; widgets' CSS uses
theme variables (`$accent`, `$border-blurred`, `$text-muted`, …). No hex value appears anywhere else. A changed
scheme draws again everything that took a role (`refresh_colours`).

**Two sets of rules.** High-colour themes use Textual's theme variables as they are. 16-colour schemes (Textual's
`App:ansi`) use only what a 16-colour terminal has: its 16 colours by name, its own foreground and background,
bold, dim, reverse, underline. Muted text is `dim`, the list's cursor is `reverse`, the unfocused cursor
`underline`; nothing is blended with transparency, which a 16-colour terminal cannot show.

**Schemes** (Settings → Colours…, applied at once; Textual's command palette changes them too):

| Scheme | Kind | |
|---|---|---|
| Terminal (default) | 16 colours | Textual's `textual-ansi`: the terminal's own palette, background and text. Light and dark follow the terminal, with no restart. |
| Midnight | 16 colours | Ours: the blue of mc and Norton Commander. |
| Console | 16 colours | Ours: black, green accents. |
| Textual dark, Textual light, Nord, Gruvbox, Solarized light, Tokyo Night | high colour | Textual's themes; they look the same in every terminal. |

A 16-colour scheme of our own is a `textual.theme.Theme` whose colours are all ANSI names (`ansi_blue`,
`ansi_bright_yellow`, …). Textual turns ANSI output on only for its own `textual-ansi`; Kram sets `ansi_color` for
its own 16-colour schemes too.

## 10. What Textual does differently (found in the spikes)

- **Textual 8 sends the app no `Resize`** when the terminal changes size (4.0 does). The layout switches on the
  resize of the panels' container instead.
- **No scrolling without a scrollbar**: `scroll_to` on a widget without one does nothing unless `force=True` (§4).
- **No escape for `[` in Textual's markup** on these versions: `\[` came out as `[[/]`. Hints are built as
  `rich.text.Text`, not markup.
- **`Button` is three lines high** and a one-line one loses its label: hence our own (T14).
- **`DataTable` keeps every cell**: fine for the repositories (dozens of rows), not for packages (T4).
- **A suspended app cannot be screenshot**: the shots show what the terminal looks like then with a stand-in screen.
- **A widget's `DEFAULT_CSS` is scoped to that widget**: a rule like `App:ansi Screen { … }` there never matches.
  Rules for other widgets belong in the app's `CSS`.
- **Colours blended with transparency vanish with 16 colours** (the footer's words, a checkbox's label): in
  `App:ansi` those widgets get plain theme colours.
- **The SVG screenshots draw the terminal's default text colour as invisible** where it is set explicitly (the
  footer's words in the Terminal scheme). In a terminal it is right (`default on default`, checked).

## 11. Spike results

The colour schemes: 6 more cases in `t1_tui.py shots` (37–42) and 3 in `t2_dialogs.py shots` (17–19); every
case is the same on both Textual versions.

Machine: Intel Core Ultra 5 125U; containers with Fedora 44 (Textual 4.0.0, Python 3.14) and Fedora 45 (Textual
8.1.1, Python 3.15), the Fedora 44 catalog pickled (70,235 rows). CPU time per step from `t1_tui.py bench` (the
headless test driver adds its own waits to the wall time, ~80–120 ms, the same for `DataTable`):

| | 52×18 | 160×50 |
|---|---|---|
| Cursor or page down | 4–5 ms | 12–14 ms |
| Drawing the lines | 0.3–0.4 ms | 1–2 ms |
| Filter (installed, upgradable, all) | 30–66 ms | 38–68 ms |
| Sort 70k by size | 63 ms | 65–122 ms |
| `DataTable`: fill 70k rows | — | 4,433 ms (4.0), 5,076 ms (8.1) |

Memory ~150 MB RSS with the catalog. The screenshot cases: 36 in `t1_tui.py shots`, 17 in `t2_dialogs.py shots`;
the focus, panels, cursor and scroll of every case are printed and were the same on both Textual versions.

## 12. Packaging (proposal)

- A fourth package `kram-tui` (`Requires: kram-common, python3-textual`), with its own command `/usr/bin/kram-tui`.
  Unlike `kram-qt`/`kram-gtk` it does not conflict and is not an `alternatives` choice for `/usr/bin/kram`: a
  terminal front end is wanted next to a GUI (SSH into the same machine).
- No desktop file (or one with `Terminal=true`, hidden).
- The settings are the GUIs' (`kram/core/settings.py`, the registry in `kram/app/preferences.py`); TUI-only ones
  (centre scrolling, pinned panels) carry the toolkit "tui", as D11 of `docs/GTK_FRONTEND.md` allows.

## 13. Open questions and not done

- Status glyphs: keep `▲ ■ □ ◆ ◇ ▼`, or ASCII letters as aptitude (`i`, `u`, `p`, …)?
- Search as a modal popup (now) or a line above the list that filters while typing, as the GUIs' search field
  (the key rule of §7 already covers a text field in the window)?
- Folding the Environments tree; the real Dependencies, Files and Changelog tabs (from `DetailsLoader`); marks
  through `MarkSet` with their actions (install, remove, …) instead of the spike's plain set; sorting by column;
  mouse.
- Spike T3 for §8, on a real system: desktop agent, SSH, virtual console, `sudo`.
- Width thresholds (100 columns, 34 rows) were picked by eye.
- Asking before closing Repositories with changes not applied; `q` with marks not applied.
