"""Settings → Colours… (docs/TUI_SPEC.md §10.17): the colour schemes (§9.4) as a list. The window behind takes the
scheme under the cursor as it moves, so the choice is made by looking; `Enter` keeps it (saved), `Esc` puts back
the scheme from before.
"""
from textual.widgets import OptionList

from ...app import preferences
from ..palette import schemes
from ..widgets import ChoiceList


class ColoursDialog(ChoiceList):
    """The screen's result: the scheme kept, or None when Esc put the old one back."""

    def __init__(self, current: str):
        """`current`: the scheme shown now."""
        super().__init__(preferences.pref(preferences.TUI_SCHEME).label, schemes(), current)
        self.before = current

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self.app.set_scheme(self.values[event.option_index], save=False)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        event.prevent_default()  # ChoiceList's own handler would dismiss a second time
        scheme = self.values[event.option_index]
        self.app.set_scheme(scheme)
        self.dismiss(scheme)

    def action_close(self) -> None:
        self.app.set_scheme(self.before, save=False)
        self.dismiss(None)
