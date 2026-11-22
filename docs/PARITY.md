# Feature parity between the front ends

`kram/app/parity.py` is the source of truth for what each front end of Kram supports. This page explains how it
works. The tests that enforce it are `tests/test_parity.py`.

## The list

- Every feature is one name in `Feature`, sorted, and prefixed by its scope: `DIALOG_` for a dialog or window,
  `DETAILS_` for the detail tabs, `LIST_` for the package list, `MARK_` for marking, `MENU_` for menus, `SETTINGS_`
  for preferences, `SIDEBAR_` for the sidebar, `SYSTEM_` for the desktop and the helper, `WINDOW_` for the main
  window. A new feature takes the prefix of its scope; a feature that fits nowhere gets a new scope, not `MISC_`.
- Every feature has a description in `DESCRIPTIONS`.
- Every front end has a table `Feature → Entry` (`QT`, `GTK`, `TUI`). Each table lists every feature: a missing one
  fails the tests.

## Support statuses

| Status | Meaning | Allowed in a released front end |
|---|---|---|
| `SUPPORTED` | Built and proved: at least one test marked `@pytest.mark.feature(Feature.X, front="…")` | yes |
| `PARTIAL` | Built, but not everything is proved; the note says what is not | yes (with the note) |
| `NOT_INTENDED` | Deliberately absent or different; the note says why | yes (with the note) |
| `PLANNED` | Not built yet, but wanted for this front end | no |
| `NOT_IMPLEMENTED` | Not built and not decided | no |

`PLANNED` and `NOT_IMPLEMENTED` differ only in intent: `PLANNED` says the feature is on the way. Neither may remain in a
released front end.

## Released and in development

`FRONTS_RELEASED` names the front ends that are released. For them, any `PLANNED` or `NOT_IMPLEMENTED` entry fails the
test run. A front end that is not in `FRONTS_RELEASED` may have `PLANNED` entries; the test checks that each entry is one
of the statuses above, and that a `SUPPORTED` entry has a marked test. Currently `qt` and `gtk` are released, and `tui`
is in development.

To release a front end: make every entry `SUPPORTED`, `PARTIAL` or `NOT_INTENDED` (with notes), then add its name to
`FRONTS_RELEASED` in the same commit.

## Proof

- A `SUPPORTED` entry needs at least one test that is marked for that front end. The marks are read from the sources
  with `ast`, so the check needs no toolkit and gives the same answer on any machine.
- A marked test for an entry that is not `SUPPORTED` fails the run: either the entry is set to `SUPPORTED`, or the mark
  is removed.
- The check proves that a test exists and is marked. It does not prove that the test checks the feature; that is what
  review is for. A test that runs only where its toolkit is installed is still checked for presence everywhere, and for
  passing only where it can run.

## Adding a feature

1. Add the name to `Feature` in its sorted place, with its scope prefix, and its description to `DESCRIPTIONS`.
2. Set its entry in every table (`QT`, `GTK`, `TUI`). Use `PLANNED` for a front end in development, and `NOT_INTENDED`
   with a note where it does not fit.
3. If you set an entry to `SUPPORTED`, mark the test that proves it.

## Adding a front end

1. Add a table `NAME: dict[Feature, Entry]` with an entry for every feature (start with `PLANNED`).
2. Add it to `FRONTS`.
3. The name is not released until it is in `FRONTS_RELEASED`.

Test run: `python3 -m pytest -q tests/test_parity.py` (the whole suite is best, see CONTRIBUTING.md).
