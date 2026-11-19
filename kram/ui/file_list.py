"""The Files tab: the package's files as a folder tree or a flat list, with a filter field."""
import os

from PySide6.QtCore import (
    QAbstractItemModel,
    QIdentityProxyModel,
    QMimeDatabase,
    QModelIndex,
    QPersistentModelIndex,
    QStringListModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QFont, QFontMetrics, QGuiApplication, QIcon, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..core.file_tree import Node, PathFilter, build_tree, path_filter
from ..i18n import _, ngettext
from .files import show_in_file_manager

FILTER_DELAY_MS = 150  # a package can have tens of thousands of files: filter once the typing pauses
PATH_ROLE = Qt.ItemDataRole.UserRole  # the full path, in both views
Index = QModelIndex | QPersistentModelIndex
DISPLAY, TOOLTIP, DECORATION = Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.DecorationRole


class FileIcons:
    """A folder icon, and file icons by the name's type (the desktop's MIME database), cached by extension: the
    views only ask for the rows they paint."""

    def __init__(self):
        self.folder = QIcon.fromTheme("folder")
        self._mime = QMimeDatabase()
        self._icons: dict[str, QIcon] = {}

    def file(self, name: str) -> QIcon:
        key = name.rpartition(".")[2] if "." in name else name
        icon = self._icons.get(key)
        if icon is None:
            mime = self._mime.mimeTypeForFile(name, QMimeDatabase.MatchMode.MatchExtension)
            icon = QIcon.fromTheme(mime.iconName(), QIcon.fromTheme(mime.genericIconName(),
                                                                    QIcon.fromTheme("text-x-generic")))
            self._icons[key] = icon
        return icon


class FileTreeModel(QAbstractItemModel):
    """A `Node` tree (kram.core.file_tree): one column, the name; the full path as the tooltip.

    The view calls index() and hasChildren() for every row when it expands them all, so they are kept short."""

    def __init__(self, icons: FileIcons, parent=None):
        super().__init__(parent)
        self.root = Node("/", "/")
        self._icons = icons
        self.installed = False  # then a folder without files in it is told apart on disk

    def set_root(self, root: Node) -> None:
        self.beginResetModel()
        self.root = root
        self.endResetModel()

    def index(self, row: int, column: int, parent: Index = QModelIndex()) -> QModelIndex:  # noqa: B008
        children = (parent.internalPointer() if parent.isValid() else self.root).children
        if column or not 0 <= row < len(children):
            return QModelIndex()
        return self.createIndex(row, 0, children[row])

    def parent(self, index: Index = QModelIndex()) -> QModelIndex:  # noqa: B008
        if not index.isValid():
            return QModelIndex()
        up = index.internalPointer().parent
        if up is None or up is self.root:
            return QModelIndex()
        return self.createIndex(up.row, 0, up)

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008
        if not parent.isValid():
            return len(self.root.children)
        return 0 if parent.column() else len(parent.internalPointer().children)

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008
        return 1

    def hasChildren(self, parent: Index = QModelIndex()) -> bool:  # noqa: B008
        return bool((parent.internalPointer() if parent.isValid() else self.root).children)

    def data(self, index: Index, role: int = DISPLAY):
        if not index.isValid():
            return None
        node: Node = index.internalPointer()
        if role == DISPLAY:
            return node.name
        if role in (TOOLTIP, PATH_ROLE):
            return node.path
        if role == DECORATION:
            folder = node.children or self.installed and os.path.isdir(node.path)
            return self._icons.folder if folder else self._icons.file(node.name)
        return None


class FlatModel(QIdentityProxyModel):
    """The list view: a QStringListModel of the full paths (all in C++, the view lays out every row) with icons."""

    def __init__(self, icons: FileIcons, parent=None):
        super().__init__(parent)
        self._icons = icons
        self.installed = False
        self._folders: set[str] = set()
        self._strings = QStringListModel(self)
        self.setSourceModel(self._strings)

    def set_paths(self, paths: list[str]) -> None:
        # a folder is what has files in it (the metadata do not say), as in the tree
        self._folders = {p.rpartition("/")[0] for p in paths}
        self._strings.setStringList(paths)

    def data(self, index: Index, role: int = DISPLAY):
        if role == DECORATION:
            path = super().data(index, DISPLAY)
            folder = path in self._folders or self.installed and os.path.isdir(path)
            return self._icons.folder if folder else self._icons.file(path.rpartition("/")[2])
        if role == PATH_ROLE:
            return super().data(index, DISPLAY)
        return super().data(index, role)


class MatchDelegate(QStyledItemDelegate):
    """While the filter is on, the part of a name it matched is bold: in the tree a file can be shown only because a
    folder above it matched, and then nothing in the file's own name is."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter: PathFilter | None = None

    def paint(self, painter, option, index) -> None:
        name, path = index.data(DISPLAY), index.data(PATH_ROLE)
        spans = self.filter.spans(path, len(path) - len(name)) if self.filter and name and path else []
        if not spans:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        opt.text = ""  # the style draws the background, selection and icon; the text is drawn here in pieces
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget) + 1  # as the style does
        rect = text_rect.adjusted(margin, 0, -margin, 0)
        group = (QPalette.ColorGroup.Normal if opt.state & QStyle.StateFlag.State_Enabled
                 else QPalette.ColorGroup.Disabled)
        if group == QPalette.ColorGroup.Normal and not opt.state & QStyle.StateFlag.State_Active:
            group = QPalette.ColorGroup.Inactive
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        bold = QFont(opt.font)
        bold.setBold(True)
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(opt.palette.color(group, role))
        x, pos = rect.left(), 0
        for begin, end in [*spans, (len(name), len(name))]:
            for piece, font in ((name[pos:begin], opt.font), (name[begin:end], bold)):
                if piece:
                    painter.setFont(font)
                    painter.drawText(x, rect.top(), rect.right() - x + 1, rect.height(),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, piece)
                    x += QFontMetrics(font).horizontalAdvance(piece)
            pos = end
        painter.restore()


class FileList(QWidget):
    """The Files tab. The tree is built when the tab is shown, not for every package the cursor passes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[str] = []
        self._installed = False
        self._stale = False  # new paths or a new filter not shown yet

        self.filter = QLineEdit()
        self.filter.setPlaceholderText(_("Filter files: text, or a pattern like *.so"))
        self.filter.setClearButtonEnabled(True)
        self._timer = QTimer(self, singleShot=True, interval=FILTER_DELAY_MS)
        self._timer.timeout.connect(self._rebuild)
        self.filter.textChanged.connect(lambda _text: self._timer.start())
        self.filter.returnPressed.connect(self._rebuild_now)

        self.tree_button = QToolButton(text=_("Tree"), checkable=True, autoRaise=True,
                                       icon=QIcon.fromTheme("view-list-tree"),
                                       toolButtonStyle=Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
                                       toolTip=_("Show the files in their folders"))
        self.list_button = QToolButton(text=_("List"), checkable=True, autoRaise=True,
                                       icon=QIcon.fromTheme("view-list-details"),
                                       toolButtonStyle=Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
                                       toolTip=_("Show the full path of every file, one per line"))
        group = QButtonGroup(self)
        group.addButton(self.tree_button)
        group.addButton(self.list_button)
        self.tree_button.setChecked(True)
        group.buttonToggled.connect(lambda _button, on: on and self._rebuild_now())
        self.count = QLabel()
        self.notice = QLabel(_("Not installed: repository metadata lists only some of the files."))
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)

        icons = FileIcons()
        self.tree_model = FileTreeModel(icons, self)
        self.flat_model = FlatModel(icons, self)
        self.view = QTreeView()
        self.view.setModel(self.tree_model)
        self.view.setHeaderHidden(True)
        self.view.setUniformRowHeights(True)  # tens of thousands of rows: no per-row height
        # not flags() in the models: the view asks every row for them, from Python that doubled the list's layout
        self.view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.delegate = MatchDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.copy_action = QAction(QIcon.fromTheme("edit-copy"), _("Copy Path"), self.view)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.copy_action.triggered.connect(self.copy_paths)
        self.view.addAction(self.copy_action)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.filter, 1)
        bar.addWidget(self.count)
        bar.addWidget(self.tree_button)
        bar.addWidget(self.list_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.notice)
        layout.addWidget(self.view, 1)

    # ---------------------------------------------------------------- state

    @property
    def tree_mode(self) -> bool:
        return self.tree_button.isChecked()

    @tree_mode.setter
    def tree_mode(self, on: bool) -> None:
        (self.tree_button if on else self.list_button).setChecked(True)

    def set_files(self, paths: list[str], complete: bool) -> None:
        """A package's files. `complete` is False for a package that is not installed: the repository metadata list
        only some of its files. The filter text stays, to look for the same file in the next package."""
        self._paths = paths
        self._installed = self.tree_model.installed = self.flat_model.installed = complete
        self.notice.setVisible(not complete)
        self._stale = True
        if self.isVisible():
            self._rebuild()

    def clear(self) -> None:
        self.set_files([], True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self._rebuild()

    def _rebuild_now(self) -> None:
        self._timer.stop()
        self._rebuild()

    def _rebuild(self) -> None:
        self._stale = False
        self.delegate.filter = f = path_filter(self.filter.text())
        paths = self._paths if f is None else [p for p in self._paths if f.match(p)]
        if self.tree_mode:
            self.tree_model.set_root(build_tree(paths))
            self.flat_model.set_paths([])
            self.view.setModel(self.tree_model)
            self.view.expandAll()  # old-school: every folder open, the filter narrows it
        else:
            self.tree_model.set_root(Node("/", "/"))
            self.flat_model.set_paths(paths)
            self.view.setModel(self.flat_model)
        self.view.setRootIsDecorated(self.tree_mode)
        if len(paths) == len(self._paths):
            self.count.setText(ngettext("{n} file", "{n} files", len(paths)).format(n=len(paths)))
        else:
            self.count.setText(ngettext("{shown} of {n} file", "{shown} of {n} files", len(self._paths))
                               .format(shown=len(paths), n=len(self._paths)))

    # ---------------------------------------------------------------- actions

    def selected_paths(self) -> list[str]:
        rows = sorted(self.view.selectionModel().selectedRows(), key=lambda i: self.view.visualRect(i).top())
        return [i.data(PATH_ROLE) for i in rows]

    def copy_paths(self) -> None:
        if paths := self.selected_paths():
            QGuiApplication.clipboard().setText("\n".join(paths))

    def _context_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        path = index.data(PATH_ROLE)
        menu = QMenu(self)
        menu.addAction(self.copy_action)
        show = menu.addAction(QIcon.fromTheme("system-file-manager"), _("Show in File Manager"),
                              lambda: show_in_file_manager(path))
        show.setEnabled(self._installed and os.path.lexists(path))
        menu.exec(self.view.viewport().mapToGlobal(pos))
