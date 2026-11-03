"""Kram — a Synaptic-style package manager for Fedora."""

# Reverse-DNS of https://github.com/elmodos/kram. Also the .desktop file name, the Wayland app_id
# and the prefix of the polkit action ids, so it must stay in sync with data/ and packaging/.
APP_ID = "io.github.elmodos.Kram"
POLKIT_HELPER_ACTION = f"{APP_ID}.helper"
HOMEPAGE = "https://github.com/elmodos/kram"
