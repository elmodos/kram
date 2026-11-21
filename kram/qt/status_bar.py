"""The main window's status bar: what is listed and marked, missing repositories, the age of the metadata (the
texts are kram.app.status)."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QStatusBar

from ..app.status import counts_text, error_text, metadata_age, missing_repos, timings_tip
from ..core.model import CatalogSnapshot


class MainStatusBar(QStatusBar):
    reposClicked = Signal()  # the warning about repositories without metadata

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = QLabel()
        self.addWidget(self._text, 1)
        # enabled repositories that could not be loaded; clicking opens Settings → Repositories
        self._repo_warning = QLabel()
        self._repo_warning.setVisible(False)
        self._repo_warning.linkActivated.connect(lambda _link: self.reposClicked.emit())
        self.addPermanentWidget(self._repo_warning)
        self._age = QLabel()
        self.addPermanentWidget(self._age)

    def text(self) -> str:
        return self._text.text()

    def set_text(self, text: str) -> None:
        self._text.setText(text)

    def show_error(self, error: BaseException) -> None:
        self.set_text(error_text(error))

    def show_catalog(self, snap: CatalogSnapshot) -> None:
        """What stays the same until the next load: the metadata age and the repositories that have none."""
        self._age.setText(metadata_age(snap.metadata_age) + "  ")
        warning = missing_repos(snap)
        self._repo_warning.setVisible(warning is not None)
        if warning is not None:
            text, tip = warning
            self._repo_warning.setText(f"⚠ <a href='repos'>{text}</a>  ")
            self._repo_warning.setToolTip(tip)

    def show_counts(self, snap: CatalogSnapshot, shown: int, to_install: int, to_remove: int,
                    ms: float | None = None) -> None:
        """The packages listed and marked; `ms`, the time the filter and search took, goes into the tooltip."""
        self.set_text(counts_text(snap, shown, to_install, to_remove))
        if ms is not None:
            self._text.setToolTip(timings_tip(snap, ms))
