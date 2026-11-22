"""The GTK front end: `python3 -m kram.gtk` from a source checkout (packaged later as its own /usr/bin/kram)."""
import sys

from . import app

if __name__ == "__main__":
    sys.exit(app.main())
