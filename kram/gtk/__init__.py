"""The GTK 4 + libadwaita front end: a view over kram.app, as kram.qt is. See docs/GTK_FRONTEND.md.

The toolkit versions are pinned here, before any module imports from gi.repository: PyGObject loads the newest
typelib it finds otherwise, and GTK 3 next to GTK 4 would mix.
"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
