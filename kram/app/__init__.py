"""The toolkit-free half of the user interface: presenters, view state, texts, action and menu definitions, ports.

Everything here is shared by the front ends (`kram.qt`, the Qt one, today) and imports no toolkit: no PySide6 and no
`gi`, which `tests/test_toolkit_free.py` enforces. Signals are `kram.core.mainloop.Signal`, the hand-off to the main
loop is `kram.core.mainloop.Post`, timers come from a `Scheduler` and questions to the user go through the `Ui` port,
each front end providing its own. All of it runs on the GUI thread. See docs/GTK_FRONTEND.md.
"""
