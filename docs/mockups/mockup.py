"""Throwaway UI mockup: renders hypothetical dnf-gui screens to PNG using real libdnf5 data."""
import sys, os
from dataclasses import dataclass, field

import libdnf5
import rpm
from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QFont, QBrush, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QTreeView, QTabWidget, QTextBrowser, QToolBar, QLineEdit, QComboBox, QLabel, QDialog,
    QDialogButtonBox, QTreeWidget, QTreeWidgetItem, QProgressBar, QPlainTextEdit, QCheckBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QStyle, QFormLayout,
)

OUT = sys.argv[1]
OFFICIAL = {"fedora", "updates", "updates-testing", "fedora-cisco-openh264", "anaconda"}

# ---------------------------------------------------------------- data

@dataclass
class Row:
    name: str
    arch: str
    inst: str = ""
    latest: str = ""
    repo: str = ""
    size: int = 0
    summary: str = ""
    origin: str = "fedora"      # fedora|copr|third|local|unknown
    status: str = "none"        # none|inst|upg|newer|orphan|unneeded
    mark: str = ""              # install|remove|upgrade|reinstall
    pkg: object = None
    versions: list = field(default_factory=list)


def classify(repo_id):
    if repo_id in OFFICIAL or (len(repo_id) == 32 and all(c in "0123456789abcdef" for c in repo_id)):
        return "fedora"
    if repo_id.startswith("copr:"):
        return "copr"
    if repo_id == "@commandline":
        return "local"
    if repo_id in ("", "<unknown>", "@System"):
        return "unknown"
    return "third"


def copr_short(repo_id):
    return "/".join(repo_id.split(":")[2:]) if repo_id.startswith("copr:") else repo_id


base = libdnf5.base.Base()
base.load_config()
base.setup()
base.get_config().cache_only = True
rs = base.get_repo_sack()
rs.create_repos_from_system_configuration()
rs.load_repos()

ARCHES = ["x86_64", "noarch"]
rows = {}
av = libdnf5.rpm.PackageQuery(base); av.filter_available(); av.filter_arch(ARCHES)
allv = {}
for p in av:
    allv.setdefault((p.get_name(), p.get_arch()), []).append((p.get_evr(), p.get_repo_id()))
av.filter_latest_evr()
for p in av:
    k = (p.get_name(), p.get_arch())
    rows[k] = Row(p.get_name(), p.get_arch(), latest=p.get_evr(), repo=p.get_repo_id(), size=p.get_install_size(),
                  summary=p.get_summary(), origin=classify(p.get_repo_id()), pkg=p, versions=allv.get(k, []))
unneeded = set()
try:
    uq = libdnf5.rpm.PackageQuery(base); uq.filter_unneeded()
    unneeded = {(p.get_name(), p.get_arch()) for p in uq}
except Exception:
    pass
iq = libdnf5.rpm.PackageQuery(base); iq.filter_installed(); iq.filter_arch(ARCHES)
for p in iq:
    k = (p.get_name(), p.get_arch())
    r = rows.get(k) or Row(p.get_name(), p.get_arch(), summary=p.get_summary(), versions=allv.get(k, []))
    cand = r.pkg
    r.inst = p.get_evr(); r.size = p.get_install_size(); r.pkg = p
    frm = p.get_from_repo_id()
    r.origin = classify(frm)
    if not r.repo:
        r.repo = frm
    if cand is None:
        r.status = "orphan"
    else:
        ev = lambda x: (x.get_epoch() or '0', x.get_version(), x.get_release())
        c = rpm.labelCompare(ev(p), ev(cand))
        r.status = "upg" if c < 0 else ("newer" if c > 0 else "inst")
    if k in unneeded:
        r.status = "unneeded"
    rows[k] = r

# fake a few upgrades so the mockup shows them (system is fully up to date right now)
def bump(evr):
    if "-" in evr:
        v, rel = evr.rsplit("-", 1)
        head, _, tail = rel.partition(".")
        try:
            return f"{v}-{int(head) + 1}.{tail}"
        except ValueError:
            pass
    return evr + ".1"

for n in ["firefox", "firefox-langpacks", "mesa-dri-drivers", "mesa-libGL", "systemd", "systemd-libs",
          "kernel", "kernel-core", "plasma-workspace", "python3", "python3-libs", "fish", "file", "findutils"]:
    for a in ARCHES:
        r = rows.get((n, a))
        if r and r.inst and r.status == "inst":
            r.latest = bump(r.inst)
            r.status = "upg"
            r.repo = "updates"

ALL = sorted((r for r in rows.values() if not r.name.endswith(('-debuginfo', '-debugsource'))), key=lambda r: (r.name, r.arch))
N_INST = sum(1 for r in ALL if r.inst)
N_UPG = sum(1 for r in ALL if r.status == "upg")


def human(n):
    for u in ("B", "kB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024

# ---------------------------------------------------------------- icons

def status_icon(r):
    pm = QPixmap(16, 16); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    rect = QRect(1, 1, 13, 13)
    green, dark = QColor("#4e8f3a"), QColor("#2f5a22")
    st, mk = r.status, r.mark
    if mk == "install":
        p.setPen(QPen(dark, 1)); p.setBrush(QColor("#e4f4dc")); p.drawRect(rect)
        p.setPen(QPen(dark, 2)); p.drawLine(4, 8, 11, 8); p.drawLine(7, 4, 7, 12)
    elif mk == "remove":
        p.setPen(QPen(QColor("#8a1f1f"), 1)); p.setBrush(QColor("#d64545")); p.drawRect(rect)
        p.setPen(QPen(Qt.white, 2)); p.drawLine(4, 4, 11, 11); p.drawLine(11, 4, 4, 11)
    elif mk == "upgrade":
        p.setPen(QPen(QColor("#1f4f8a"), 1)); p.setBrush(QColor("#3d7fd6")); p.drawRect(rect)
        p.setPen(QPen(Qt.white, 2)); p.drawLine(7, 12, 7, 4); p.drawLine(4, 7, 7, 4); p.drawLine(10, 7, 7, 4)
    elif st == "none":
        p.setPen(QPen(QColor("#888"), 1)); p.setBrush(Qt.white); p.drawRect(rect)
    else:
        p.setPen(QPen(dark, 1)); p.setBrush(green); p.drawRect(rect)
        p.setPen(QPen(Qt.white, 2))
        if st == "upg":
            p.setBrush(QColor("#e0a020")); p.setPen(QPen(QColor("#8a5a00"), 1)); p.drawRect(rect)
            p.setPen(QPen(Qt.white, 2)); p.drawLine(7, 12, 7, 4); p.drawLine(4, 7, 7, 4); p.drawLine(10, 7, 7, 4)
        elif st == "orphan":
            p.setFont(QFont("Noto Sans", 8, QFont.Bold)); p.drawText(rect, Qt.AlignCenter, "?")
        elif st == "unneeded":
            p.setBrush(QColor("#9bb98f")); p.setPen(QPen(dark, 1)); p.drawRect(rect)
            p.setPen(QPen(Qt.white, 3)); p.drawPoint(7, 7)
    p.end()
    return QIcon(pm)


ORIGIN_STYLE = {"fedora": ("#294172", "F"), "copr": ("#d4762c", "C"), "third": ("#6b6b6b", "3"),
                "local": ("#7a4fa0", "L"), "unknown": ("#b03030", "?")}


def origin_icon(origin):
    color, ch = ORIGIN_STYLE[origin]
    pm = QPixmap(16, 16); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color)); p.setPen(Qt.NoPen); p.drawEllipse(1, 1, 14, 14)
    p.setPen(Qt.white); p.setFont(QFont("Noto Sans", 7, QFont.Bold)); p.drawText(QRect(1, 1, 14, 14), Qt.AlignCenter, ch)
    p.end()
    return QIcon(pm)


ORIGIN_NAME = {"fedora": "Fedora", "copr": "COPR", "third": "Стороннє", "local": "Локальне", "unknown": "Невідоме"}
MARK_BG = {"install": (90, 170, 60, 70), "remove": (210, 60, 60, 80), "upgrade": (60, 130, 220, 70), "reinstall": (200, 170, 50, 70)}

# ---------------------------------------------------------------- main window

def details_html(r, tab):
    p = r.pkg
    if tab == "desc":
        return (f"<h3 style='margin:0'>{r.summary}</h3><p>{(p.get_description() or '').replace(chr(10)+chr(10), '<p>')}</p>")
    if tab == "deps":
        def lst(title, rl, limit=14):
            items = [x.to_string() if hasattr(x, "to_string") else str(x) for x in rl][:limit]
            return f"<b>{title}</b><ul style='margin-top:2px'>" + "".join(
                f"<li><a href='#'>{i}</a></li>" for i in items) + "</ul>"
        return lst("Залежить від (Requires):", p.get_requires()) + lst("Рекомендує (Recommends):", p.get_recommends(), 6)
    return ""


class MainWin(QMainWindow):
    def __init__(self, sidebar_mode, sidebar_items, sidebar_sel, rows_, sel_name, tab, search="", search_mode=0, sort=True):
        super().__init__()
        self.setWindowTitle("Менеджер пакунків — dnf-gui")
        self.resize(1320, 860)
        mb = self.menuBar()
        for m in ["&Файл", "&Правка", "Па&кунок", "&Налаштування", "&Довідка"]:
            mb.addMenu(m)

        tb = QToolBar(); tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon); tb.setIconSize(QSize(24, 24)); tb.setMovable(False)
        tb.addAction(QIcon.fromTheme("view-refresh"), "Перечитати")
        tb.addAction(QIcon.fromTheme("system-software-update"), "Позначити всі оновлення")
        apply_ = tb.addAction(QIcon.fromTheme("dialog-ok-apply"), "Застосувати")
        apply_.setEnabled(any(r.mark for r in ALL))
        tb.addSeparator()
        tb.addAction(QIcon.fromTheme("document-properties"), "Властивості")
        tb.addAction(QIcon.fromTheme("configure"), "Репозиторії")
        spacer = QWidget(); spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy().Preferred)
        tb.addWidget(spacer)
        mode = QComboBox(); mode.addItems(["Назва", "Назва + опис", "Повний опис", "Provides", "Файл"]); mode.setCurrentIndex(search_mode)
        tb.addWidget(mode)
        se = QLineEdit(search); se.setPlaceholderText("Пошук (Ctrl+F)"); se.setClearButtonEnabled(True); se.setFixedWidth(280)
        se.addAction(QIcon.fromTheme("edit-find"), QLineEdit.LeadingPosition)
        tb.addWidget(se)
        self.addToolBar(tb)

        # sidebar
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(4, 4, 0, 4)
        lst = QListWidget()
        for text, count, *icon in sidebar_items:
            it = QListWidgetItem(f"{text}" + (f"   ({count})" if count is not None else ""))
            if icon:
                it.setIcon(icon[0])
            if text.startswith("  "):
                pass
            if text == sidebar_items[0][0]:
                f = it.font(); f.setBold(True); it.setFont(f)
            lst.addItem(it)
            if text == sidebar_sel:
                lst.setCurrentItem(it)
        lv.addWidget(lst, 1)
        for b in ["Статус", "Походження", "Групи", "Результати пошуку", "Власні фільтри"]:
            btn = QPushButton(b); btn.setCheckable(True); btn.setChecked(b == sidebar_mode)
            lv.addWidget(btn)

        # table
        model = QStandardItemModel(0, 8)
        model.setHorizontalHeaderLabels(["S", "", "Пакунок", "Встановлена версія", "Остання версія", "Репозиторій", "Розмір", "Опис"])
        sel_idx = None
        for i, r in enumerate(rows_):
            s = QStandardItem(); s.setIcon(status_icon(r))
            o = QStandardItem(); o.setIcon(origin_icon(r.origin)); o.setToolTip(ORIGIN_NAME[r.origin])
            nm = QStandardItem(r.name if r.arch != "noarch" or True else r.name)
            cells = [s, o, nm, QStandardItem(r.inst), QStandardItem(r.latest), QStandardItem(copr_short(r.repo)),
                     QStandardItem(human(r.size) if r.size else ""), QStandardItem(r.summary)]
            cells[6].setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if r.status == "upg":
                cells[4].setForeground(QBrush(QColor("#b06d00"))); f = cells[4].font(); f.setBold(True); cells[4].setFont(f)
            if r.mark:
                for c in cells:
                    c.setBackground(QColor(*MARK_BG[r.mark]))
            model.appendRow(cells)
            if r.name == sel_name and sel_idx is None:
                sel_idx = i
        tv = QTreeView(); tv.setModel(model); tv.setRootIsDecorated(False); tv.setAlternatingRowColors(True)
        tv.setUniformRowHeights(True); tv.setSelectionBehavior(QAbstractItemView.SelectRows); tv.header().setSortIndicatorShown(sort)
        tv.header().setSortIndicator(2, Qt.AscendingOrder)
        for c, w in enumerate([26, 24, 220, 165, 165, 150, 80]):
            tv.setColumnWidth(c, w)
        tv.header().setStretchLastSection(True)
        if sel_idx is not None:
            tv.setCurrentIndex(model.index(sel_idx, 2))
            tv.scrollTo(model.index(sel_idx, 2))

        # details
        tabs = QTabWidget()
        sel = rows_[sel_idx] if sel_idx is not None else rows_[0]
        for key, title in [("desc", "Опис"), ("gen", "Загальне"), ("deps", "Залежності"), ("files", "Файли"),
                           ("ver", "Версії"), ("log", "Changelog")]:
            if key == "gen":
                w = QWidget(); fl = QFormLayout(w); p = sel.pkg
                for k, v in [("Пакунок", p.get_nevra()), ("Походження", f"{ORIGIN_NAME[sel.origin]} — {copr_short(sel.repo)}"),
                             ("Ліцензія", p.get_license()), ("Сайт", p.get_url()), ("Пакувальник", p.get_packager() or "Fedora Project"),
                             ("Встановлено", "вручну (користувачем)" if sel.inst else "—")]:
                    fl.addRow(QLabel(f"<b>{k}:</b>"), QLabel(v))
            elif key == "ver":
                w = QTableWidget(len(sel.versions) + (1 if sel.inst else 0), 3)
                w.setHorizontalHeaderLabels(["Версія", "Репозиторій", ""])
                i = 0
                if sel.inst:
                    for c, t in enumerate([sel.inst, "@System", "встановлено"]):
                        w.setItem(0, c, QTableWidgetItem(t))
                    i = 1
                for evr, repo in sorted(sel.versions, reverse=True):
                    w.setItem(i, 0, QTableWidgetItem(evr)); w.setItem(i, 1, QTableWidgetItem(copr_short(repo)))
                    w.setItem(i, 2, QTableWidgetItem("кандидат" if evr == sel.latest else "")); i += 1
                w.horizontalHeader().setStretchLastSection(True); w.setColumnWidth(0, 260); w.setColumnWidth(1, 360)
                w.verticalHeader().hide()
            else:
                w = QTextBrowser(); w.setHtml(details_html(sel, key))
            tabs.addTab(w, title)
        tabs.setCurrentIndex({"desc": 0, "gen": 1, "deps": 2, "ver": 4}[tab])

        vs = QSplitter(Qt.Vertical); vs.addWidget(tv); vs.addWidget(tabs); vs.setSizes([520, 260])
        hs = QSplitter(Qt.Horizontal); hs.addWidget(left); hs.addWidget(vs); hs.setSizes([270, 1050])
        self.setCentralWidget(hs)

        to_inst = sum(1 for r in ALL if r.mark in ("install", "upgrade", "reinstall"))
        to_rm = sum(1 for r in ALL if r.mark == "remove")
        self.statusBar().showMessage(
            f"{len(rows_)} показано, {N_INST} встановлено, {N_UPG} оновлень. "
            f"{to_inst} до встановлення/оновлення, {to_rm} до видалення.")
        cache = QLabel("Метадані: 37 хв тому  "); self.statusBar().addPermanentWidget(cache)


def shoot(w, name):
    w.show(); QApplication.processEvents()
    w.grab().save(os.path.join(OUT, name))
    print("saved", name)


def status_items(sel):
    def cnt(f): return sum(1 for r in ALL if f(r))
    return [("Усі", len(ALL)), ("Встановлені", N_INST), ("Не встановлені", len(ALL) - N_INST),
            ("Оновлювані", N_UPG), ("Встановлені вручну", None), ("Непотрібні залежності", cnt(lambda r: r.status == "unneeded")),
            ("Осиротілі (без репо)", cnt(lambda r: r.status == "orphan")), ("Новіші за репо", 0),
            ("Позначені", cnt(lambda r: bool(r.mark)))]


app = QApplication(sys.argv)
app.setStyle("Breeze")
app.setPalette(app.style().standardPalette())
QIcon.setThemeName("breeze")
app.setFont(QFont("Noto Sans", 10))

R = {(r.name, r.arch): r for r in ALL}
def mark(name, m, arch="x86_64"):
    r = R.get((name, arch)) or R.get((name, "noarch"))
    if r:
        r.mark = m
    return r

# ---- 1. main: Status/All around "fi*"
mark("fish", "install"); mark("firefox", "upgrade"); mark("firefox-langpacks", "upgrade")
mark("firewall-config", "remove", "noarch")
for r in []:
    if r.name.startswith("fi") and r.status in ("inst", "unneeded") and "lib" not in r.name and r.name not in ("firefox", "file", "findutils", "filesystem"):
        r.mark = "remove"; break
start = next(i for i, r in enumerate(ALL) if r.name >= "firefox") - 6
shoot(MainWin("Статус", status_items("Усі"), "Усі", ALL[start:start + 60], "firefox", "desc"), "01-main-all.png")

# ---- 2. search
q = "terminal"
def rank(r):
    n = r.name.lower()
    if n == q: return 0
    if n.startswith(q): return 1
    if q in n: return 2
    if q in r.summary.lower(): return 3
    return 9
res = sorted((r for r in ALL if rank(r) < 9), key=lambda r: (rank(r), not r.inst, r.name))
hist = [("Результати пошуку", None), (f"«{q}» — назва + опис", len(res)), ("«wezterm» — назва", 3),
        ("«libvulkan» — provides", 12), ("«/usr/bin/7z» — файл", 1)]
shoot(MainWin("Результати пошуку", hist, f"«{q}» — назва + опис", res[:80], res[0].name, "deps", q, 1, sort=False), "02-search.png")

# ---- 3. origin: COPR
coprs = {}
third = {}
for r in ALL:
    if r.origin == "copr":
        coprs.setdefault(copr_short(r.repo), []).append(r)
    elif r.origin == "third":
        third.setdefault(r.repo, []).append(r)
ci = lambda o: origin_icon(o)
items = [("Усі походження", len(ALL)), ("Fedora (офіційне)", sum(1 for r in ALL if r.origin == "fedora"), ci("fedora")),
         ("COPR", sum(len(v) for v in coprs.values()), ci("copr"))]
items += [(f"    {k}", len(v), ci("copr")) for k, v in sorted(coprs.items())]
items += [("Сторонні", sum(len(v) for v in third.values()), ci("third"))]
items += [(f"    {k}", len(v), ci("third")) for k, v in sorted(third.items(), key=lambda kv: -len(kv[1]))[:8]]
items += [("Локальні (@commandline)", sum(1 for r in ALL if r.origin == "local"), ci("local")),
          ("Невідомі (репо зникло)", sum(1 for r in ALL if r.origin == "unknown"), ci("unknown"))]
copr_rows = sorted((r for v in coprs.values() for r in v), key=lambda r: (not r.inst, r.name))
sel_copr = next((r.name for r in copr_rows if r.inst), copr_rows[0].name)
shoot(MainWin("Походження", items, "COPR", copr_rows, sel_copr, "ver"), "03-origin-copr.png")

# ---- 4. apply dialog (real resolve for the marked packages)
d = QDialog(); d.setWindowTitle("Застосувати зміни"); d.resize(760, 600)
v = QVBoxLayout(d)
v.addWidget(QLabel("<b>Буде виконано такі зміни.</b> Перевірте список перед застосуванням."))
tw = QTreeWidget(); tw.setHeaderLabels(["Пакунок", "Версія", "Репозиторій", "Розмір"]); tw.setColumnWidth(0, 300); tw.setColumnWidth(1, 200)
groups = {"install": [], "dep": [], "upgrade": [], "remove": []}
try:
    goal = libdnf5.base.Goal(base)
    goal.add_install("fish")
    tr = goal.resolve()
    for tp in tr.get_transaction_packages():
        p = tp.get_package()
        key = "install" if p.get_name() == "fish" else "dep"
        groups[key].append((p.get_name(), p.get_evr(), p.get_repo_id(), p.get_download_size()))
except Exception as e:
    print("resolve failed:", e)
for n in ("firefox", "firefox-langpacks"):
    r = R.get((n, "x86_64"))
    if r: groups["upgrade"].append((r.name, f"{r.inst} → {r.latest}", "updates", r.size // 3))
for r in ALL:
    if r.mark == "remove":
        groups["remove"].append((r.name, r.inst, copr_short(r.repo), r.size))
labels = {"install": ("Буде встановлено", "#2f7a1f"), "dep": ("Буде встановлено як залежності", "#2f7a1f"),
          "upgrade": ("Буде оновлено", "#1f4f8a"), "remove": ("Буде видалено", "#a02020")}
for k, items_ in groups.items():
    if not items_: continue
    top = QTreeWidgetItem([f"{labels[k][0]} ({len(items_)})"]); f = top.font(0); f.setBold(True); top.setFont(0, f)
    top.setForeground(0, QBrush(QColor(labels[k][1])))
    for n, ver, repo, sz in items_:
        QTreeWidgetItem(top, [n, ver, repo, human(sz)])
    tw.addTopLevelItem(top); top.setExpanded(True)
v.addWidget(tw, 1)
tot = sum(sz for k in ("install", "dep", "upgrade") for *_, sz in groups[k])
v.addWidget(QLabel(f"Буде завантажено: <b>{human(tot)}</b>.   Після операції буде використано додатково: <b>{human(tot * 3)}</b>."))
cmd = QPlainTextEdit("dnf5 install fish\ndnf5 upgrade firefox firefox-langpacks" +
                     ("\ndnf5 remove " + " ".join(n for n, *_ in groups["remove"]) if groups["remove"] else ""))
cmd.setReadOnly(True); cmd.setFixedHeight(70); cmd.setFont(QFont("Noto Sans Mono", 9))
gb = QGroupBox("Еквівалентна команда"); gl = QVBoxLayout(gb); gl.addWidget(cmd); v.addWidget(gb)
v.addWidget(QCheckBox("Лише завантажити пакунки"))
bb = QDialogButtonBox(); bb.addButton("Скасувати", QDialogButtonBox.RejectRole)
ok = bb.addButton("Застосувати", QDialogButtonBox.AcceptRole); ok.setIcon(QIcon.fromTheme("dialog-ok-apply")); ok.setDefault(True)
v.addWidget(bb)
shoot(d, "04-apply-preview.png")

# ---- 5. COPR dialog
d = QDialog(); d.setWindowTitle("Репозиторії COPR"); d.resize(860, 620)
v = QVBoxLayout(d)
v.addWidget(QLabel("<b>Підключені проєкти</b>"))
copr_repos = [r for r in rs.get_data()] if hasattr(rs, "get_data") else []
rq = libdnf5.repo.RepoQuery(base)
crs = sorted([r for r in rq if r.get_id().startswith("copr:")], key=lambda r: r.get_id())
t = QTableWidget(len(crs), 5); t.setHorizontalHeaderLabels(["Увімк.", "Проєкт", "Хаб", "Пакунків", "Встановлено"])
for i, r in enumerate(crs):
    cb = QTableWidgetItem(); cb.setCheckState(Qt.Checked if r.is_enabled() else Qt.Unchecked); t.setItem(i, 0, cb)
    parts = r.get_id().split(":")
    t.setItem(i, 1, QTableWidgetItem("/".join(parts[2:]))); t.setItem(i, 2, QTableWidgetItem(parts[1]))
    rid = r.get_id()
    t.setItem(i, 3, QTableWidgetItem(str(sum(1 for x in ALL if x.repo == rid))))
    t.setItem(i, 4, QTableWidgetItem(str(sum(1 for x in ALL if x.repo == rid and x.inst))))
t.verticalHeader().hide(); t.horizontalHeader().setStretchLastSection(True); t.setColumnWidth(0, 60); t.setColumnWidth(1, 330); t.setColumnWidth(2, 220)
t.setSelectionBehavior(QAbstractItemView.SelectRows); t.selectRow(0); t.setFixedHeight(150)
v.addWidget(t)
hb = QHBoxLayout()
for txt, ic in [("Увімкнути", "checkbox"), ("Вимкнути", "dialog-cancel"), ("Видалити…", "edit-delete"), ("Показати пакунки", "view-list-details")]:
    hb.addWidget(QPushButton(QIcon.fromTheme(ic), txt))
hb.addStretch(); v.addLayout(hb)
v.addSpacing(10)
v.addWidget(QLabel("<b>Додати проєкт</b>"))
hb = QHBoxLayout(); e = QLineEdit("hyprland"); e.setPlaceholderText("owner/project або пошуковий запит"); hb.addWidget(e, 1)
hb.addWidget(QPushButton(QIcon.fromTheme("edit-find"), "Знайти в Copr")); v.addLayout(hb)
res_ = [("solopasha/hyprland", "Hyprland compositor and ecosystem", "fedora-44 ✓", "1.2k"),
        ("lionheartp/Hyprland", "Hyprland and related tools", "fedora-44 ✓", "310"),
        ("someuser/hyprland-git", "Nightly git builds of Hyprland", "fedora-43 ✗", "42"),
        ("another/hypr-extras", "Plugins and extra utilities", "fedora-44 ✓", "17")]
t2 = QTableWidget(len(res_), 4); t2.setHorizontalHeaderLabels(["Проєкт", "Опис", "Chroot", "★"])
for i, row in enumerate(res_):
    for c, val in enumerate(row):
        it = QTableWidgetItem(val)
        if c == 2 and "✗" in val: it.setForeground(QBrush(QColor("#a02020")))
        t2.setItem(i, c, it)
t2.verticalHeader().hide(); t2.setColumnWidth(0, 230); t2.setColumnWidth(1, 380); t2.setColumnWidth(2, 120)
t2.horizontalHeader().setStretchLastSection(True); t2.setSelectionBehavior(QAbstractItemView.SelectRows); t2.selectRow(0)
v.addWidget(t2, 1)
warn = QLabel("ⓘ Проєкти COPR збирають сторонні люди; Fedora їх не перевіряє.")
warn.setStyleSheet("color:#666"); v.addWidget(warn)
bb = QDialogButtonBox(); add = bb.addButton("Підключити вибраний", QDialogButtonBox.ActionRole); add.setIcon(QIcon.fromTheme("list-add"))
bb.addButton("Закрити", QDialogButtonBox.RejectRole); v.addWidget(bb)
shoot(d, "05-copr.png")

# ---- 6. repositories dialog
d = QDialog(); d.setWindowTitle("Репозиторії"); d.resize(900, 560)
v = QVBoxLayout(d)
hb = QHBoxLayout(); hb.addWidget(QLineEdit(placeholderText="Фільтр…"), 1); cb = QCheckBox("Показати debuginfo/source"); hb.addWidget(cb); v.addLayout(hb)
allr = sorted([r for r in rq if not r.get_id().endswith(("-debuginfo", "-source")) and not r.get_id().startswith("@")], key=lambda r: (not r.is_enabled(), r.get_id()))
t = QTableWidget(len(allr), 5); t.setHorizontalHeaderLabels(["Увімк.", "ID", "Назва", "Пріоритет", "Тип"])
for i, r in enumerate(allr):
    c0 = QTableWidgetItem(); c0.setCheckState(Qt.Checked if r.is_enabled() else Qt.Unchecked); t.setItem(i, 0, c0)
    t.setItem(i, 1, QTableWidgetItem(r.get_id())); t.setItem(i, 2, QTableWidgetItem(r.get_name()))
    t.setItem(i, 3, QTableWidgetItem(str(r.get_priority())))
    o = classify(r.get_id()); t.setItem(i, 4, QTableWidgetItem(ORIGIN_NAME[o])); t.item(i, 4).setIcon(origin_icon(o))
t.verticalHeader().hide(); t.setColumnWidth(0, 60); t.setColumnWidth(1, 320); t.setColumnWidth(2, 300); t.setColumnWidth(3, 80)
t.horizontalHeader().setStretchLastSection(True); t.setSelectionBehavior(QAbstractItemView.SelectRows)
v.addWidget(t, 1)
bb = QDialogButtonBox(); bb.addButton("Перечитати метадані", QDialogButtonBox.ActionRole); bb.addButton("Закрити", QDialogButtonBox.RejectRole)
v.addWidget(bb)
shoot(d, "06-repos.png")

# ---- 7. progress
d = QDialog(); d.setWindowTitle("Застосування змін"); d.resize(680, 420)
v = QVBoxLayout(d)
v.addWidget(QLabel("<b>Встановлення пакунків</b>"))
FF = R[("firefox","x86_64")].latest; FI = (R.get(("fish","x86_64")) or R[("fish","noarch")]).latest
v.addWidget(QLabel(f"Крок 2 з 3: rpm — оновлення firefox-{FF}.x86_64"))
pb = QProgressBar(); pb.setValue(63); v.addWidget(pb)
v.addWidget(QLabel("Завантажено 120.1 MB з 120.1 MB"))
pb2 = QProgressBar(); pb2.setValue(100); v.addWidget(pb2)
log = QPlainTextEdit(); log.setReadOnly(True); log.setFont(QFont("Noto Sans Mono", 9))
log.setPlainText(f"[1/4] fish-{FI}.x86_64          100% |  12.1 MiB/s |   5.1 MiB\n"
                 f"[2/4] ncurses-term                     100% |   9.8 MiB/s |   1.0 MiB\n"
                 f"[3/4] firefox-langpacks-{FF}  100% |  18.9 MiB/s |  16.3 MiB\n"
                 f"[4/4] firefox-{FF}.x86_64     100% |  22.4 MiB/s |  97.8 MiB\n"
                 "Перевірка пакунків…  OK\nПеревірка транзакції…  OK\n"
                 "Запуск транзакції\n  Підготовка                              100%\n"
                 f"  Встановлення fish-{FI}.x86_64     100%\n"
                 f"  Встановлення ncurses-term                100%\n"
                 f"  Оновлення firefox-{FF}.x86_64     63%")
gb = QGroupBox("Подробиці"); gl = QVBoxLayout(gb); gl.addWidget(log); v.addWidget(gb, 1)
v.addWidget(QCheckBox("Закрити після успішного завершення"))
bb = QDialogButtonBox(); x = bb.addButton("Закрити", QDialogButtonBox.RejectRole); x.setEnabled(False); v.addWidget(bb)
shoot(d, "07-progress.png")
