"""The Custom Filters dialog as kram.app.custom_filters wants it."""
from PySide6.QtWidgets import QWidget

from ..app.custom_filters import EditDialog
from .filters_dialog import FiltersDialog


def edit_dialog(parent: QWidget) -> EditDialog:
    def show(filters, snap, select, new, resolve_provides, done):
        d = FiltersDialog(filters, snap, parent, select=select, new=new, resolve_provides=resolve_provides)
        accepted = d.exec()
        result = (d.filters(), d.current_name()) if accepted else None
        d.deleteLater()
        done(result)
    return show
