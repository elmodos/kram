"""'Apply changes' preview for GTK (kram.app.apply_review): everything the transaction will do, dependencies included,
before anything runs. The view of ApplyReview, as kram.qt.apply_dialog is."""
from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk, Pango

from ...app.apply_review import ApplyReview, ChangeRow, ChangeSection, Recommendations, RecRow, Resolver
from ...app.doc import Span
from ...core.model import TransactionPreview
from ...i18n import _
from .. import icons
from ..doc_view import spans_markup
from .common import Node, column, frame, label, standard_button, text_view, tree_model, wrapped


def _section_markup(section: ChangeSection) -> str:
    title = f"<b>{GLib.markup_escape_text(section.title)}</b>"
    return f"<span foreground='{section.color}'>{title}</span>" if section.color else title


class ChangesTree(Gtk.ScrolledWindow):
    """Every package a transaction touches, grouped by what happens to it."""

    def __init__(self):
        super().__init__(vexpand=True)
        self.view = Gtk.ColumnView(reorderable=False)
        self.view.add_css_class("data-table")
        self.set_child(self.view)

        def setup_name() -> Gtk.Widget:
            box = Gtk.Box(spacing=6)
            box.append(Gtk.Image())
            box.append(label())
            return box

        def bind_name(box: Gtk.Box, node: Node) -> None:
            image, text = box.get_first_child(), box.get_last_child()
            if isinstance(node.data, ChangeSection):
                image.set_visible(False)
                text.set_markup(_section_markup(node.data))
                box.set_tooltip_text(None)
                return
            row: ChangeRow = node.data
            text.set_text(row.name)
            if row.group_id:
                icons.set_image(image, ("group", row.group_id))
                box.set_tooltip_text(row.group_id)
            elif row.warning:
                image.set_from_icon_name("dialog-warning-symbolic")
                box.set_tooltip_text(row.warning)
            else:
                image.clear()
                box.set_tooltip_text(None)
            image.set_visible(bool(row.group_id or row.warning))

        def text_of(field: str, tip: bool = False):
            def bind(widget: Gtk.Label, node: Node) -> None:
                value = getattr(node.data, field, "") if isinstance(node.data, ChangeRow) else ""
                widget.set_text(value)
                widget.set_tooltip_text(value if tip and value else None)
            return bind

        self.name_column = column(self.view, _("Package"), setup_name, bind_name, tree=True)
        # the name is what the user reads; a long version ("… → …") gives way instead, keeping both ends
        column(self.view, _("Version"), lambda: label(Pango.EllipsizeMode.MIDDLE), text_of("version", tip=True),
               expand=True)
        column(self.view, _("Repository"), label, text_of("repo"))
        column(self.view, _("Size"), lambda: label(numeric=True), text_of("size"))

    def show_sections(self, sections: list[ChangeSection]) -> None:
        nodes = [Node(s, [Node(r) for r in s.rows]) for s in sections]
        self.view.set_model(Gtk.NoSelection(model=tree_model(nodes)))


class RecommendationsList(Gtk.Box):
    """The recommendations (kram.app.apply_review.Recommendations) with a checkbox each; `on_toggled()` after the
    user changed one, for the owner to resolve again and show the rows of the result."""

    def __init__(self, model: Recommendations):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.model = model
        self.on_toggled: Callable[[], None] = lambda: None
        hint = wrapped()
        hint.set_markup("<b>{}</b> {}".format(
            GLib.markup_escape_text(_("Recommended packages.")),
            GLib.markup_escape_text(_("Not required, but suggested by the packages being installed. "
                                      "Uncheck what you do not want."))))
        self.append(hint)
        self.view = Gtk.ColumnView()
        self.view.add_css_class("data-table")
        self.append(Gtk.ScrolledWindow(child=self.view, vexpand=True))
        self._nested_open = False

        def setup_check() -> Gtk.Widget:
            box = Gtk.Box(spacing=6)
            check = Gtk.CheckButton()
            check.connect("toggled", self._toggled)
            box.append(check)
            box.append(label())
            return box

        def bind_check(box: Gtk.Box, node: Node) -> None:
            check, text = box.get_first_child(), box.get_last_child()
            check.node = None  # no "toggled" from filling it
            if isinstance(node.data, RecRow):
                row: RecRow = node.data
                check.set_visible(True)
                check.set_active(row.rec.checked)
                check.node = node
                text.set_text(row.label)
                box.set_tooltip_text(row.tip)
            else:
                check.set_visible(False)
                text.set_text(node.data)
                box.set_tooltip_text(None)

        def text_of(field: str):
            def bind(widget: Gtk.Label, node: Node) -> None:
                widget.set_text(getattr(node.data, field) if isinstance(node.data, RecRow) else "")
            return bind

        column(self.view, _("Recommended package"), setup_check, bind_check, tree=True)
        column(self.view, _("Recommended by"), label, text_of("by"), expand=True)
        column(self.view, _("Adds"), label, text_of("adds"))

    def _toggled(self, check: Gtk.CheckButton) -> None:
        node = getattr(check, "node", None)
        if node is None or node.data.rec.checked == check.get_active():
            return
        self.model.set_checked(node.data.rec, check.get_active())
        self.on_toggled()

    def _remember_open(self) -> None:
        model = self.view.get_model()
        if model is None:
            return
        tree = model.get_model()
        for i in range(tree.get_n_items()):
            row = tree.get_row(i)
            if row is not None and row.get_item().children:
                self._nested_open = row.get_expanded()

    def show_rows(self, direct: list[RecRow], nested: list[RecRow]) -> None:
        self._remember_open()
        nodes = [Node(r) for r in direct]
        if nested:
            nodes.append(Node(self.model.nested_title(len(nested)), [Node(r) for r in nested]))
        keep_open = self._nested_open or not direct
        self.view.set_model(Gtk.NoSelection(model=tree_model(nodes, lambda _n: keep_open)))


class ApplyDialog(Adw.Dialog):
    """`done(request)` once it closes: the request to run, or None when cancelled."""

    def __init__(self, preview: TransactionPreview, request: dict, basearch: str,
                 done: Callable[[dict | None], None], resolve: Resolver | None = None):
        super().__init__(title=_("Apply changes"), content_width=820, content_height=680)
        self._done = done
        self._accepted = False
        self.review = ApplyReview(preview, request, basearch, self, resolve)
        header, body = frame(self)

        cancel = standard_button("_Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        header.pack_start(cancel)
        self.ok = Gtk.Button(label=_("Apply"))
        self.ok.add_css_class("suggested-action")
        self.ok.connect("clicked", self._apply)
        header.pack_end(self.ok)
        self.set_default_widget(self.ok)

        intro = wrapped()
        intro.set_markup("<b>{}</b> {}".format(GLib.markup_escape_text(_("The following changes will be made.")),
                                               GLib.markup_escape_text(_("Review the list before applying."))))
        body.append(intro)

        # marked changes the resolver left out (see TransactionPreview.skipped): above the list, so it is not missed
        self.skipped_label = wrapped("error")
        body.append(self.skipped_label)
        self.skipped_box, self.skipped_text = text_view(110)
        body.append(self.skipped_box)

        self.tree = ChangesTree()
        self.recs_box = RecommendationsList(self.review.recs)
        self.recs_box.on_toggled = self.review.recs_changed
        self.recs = self.recs_box.view
        if preview.recommendations:
            split = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, start_child=self.tree, end_child=self.recs_box,
                              shrink_start_child=False, shrink_end_child=False, vexpand=True, position=340)
            body.append(split)
        else:
            body.append(self.tree)

        self.sizes = wrapped()
        body.append(self.sizes)
        # groups whose packages are already in place: why the list has no packages (see groups_only_note)
        self.note = wrapped()
        body.append(self.note)
        self.warning = wrapped("error")
        body.append(self.warning)
        # not enough free space: Apply stays off
        self.space = wrapped("error")
        body.append(self.space)

        command_title = Gtk.Label(label=_("Equivalent command"), xalign=0)
        command_title.add_css_class("heading")
        body.append(command_title)
        command_box, self.cmd = text_view(64)
        self.cmd.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        body.append(command_box)

        self.download_only = Gtk.CheckButton(label=_("Download packages only"))
        self.download_only.connect("toggled", lambda b: self.review.set_download_only(b.get_active()))
        body.append(self.download_only)

        self.connect("closed", self._closed)
        self.review.start()

    @property
    def request(self) -> dict:
        """With the recommendations the user unchecked."""
        return self.review.request

    def _apply(self, _button) -> None:
        if self.ok.get_sensitive():
            self._accepted = True
            self.close()

    def _closed(self, _dialog) -> None:
        self.review.close()  # results that arrive later are dropped
        result = self.review.result() if self._accepted else None
        done, self._done = self._done, None
        if done is not None:
            done(result)

    # ---------------------------------------------------------------- ApplyReviewView

    def show_preview(self, preview, sections, recs) -> None:
        self.tree.show_sections(sections)
        self.recs_box.show_rows(*recs)

    @staticmethod
    def _set(widget: Gtk.Label, text: str, markup: bool = False) -> None:
        if markup:
            widget.set_markup(text)
        else:
            widget.set_text(text)
        widget.set_visible(bool(text))

    def show_texts(self, sizes: list[Span], note: str, warning: str, skipped_title: str, skipped: str) -> None:
        self._set(self.sizes, spans_markup(sizes), markup=True)
        self._set(self.note, note)
        self._set(self.warning, f"<b>{GLib.markup_escape_text(warning)}</b>" if warning else "", markup=True)
        self._set(self.skipped_label,
                  f"<b>{GLib.markup_escape_text(skipped_title)}</b>" if skipped_title else "", markup=True)
        self.skipped_text.get_buffer().set_text(skipped)
        self.skipped_box.set_visible(bool(skipped))

    def show_space(self, text: str) -> None:
        self._set(self.space, f"<b>{GLib.markup_escape_text(text)}</b>" if text else "", markup=True)

    def show_command(self, text: str) -> None:
        self.cmd.get_buffer().set_text(text)

    def set_can_apply(self, on: bool) -> None:
        self.ok.set_sensitive(on)

    def set_resolving(self, busy: bool, text: str | None = None) -> None:
        self.recs.set_sensitive(not busy)
        if text is not None:
            self._set(self.sizes, text)
