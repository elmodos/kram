"""Kram — a Synaptic-style package manager for Fedora."""
# SPDX-License-Identifier: GPL-3.0-or-later

__version__ = "0.1.4"  # keep in sync with pyproject.toml and packaging/kram.spec

# Reverse-DNS of https://github.com/elmodos/kram. Also the .desktop file name, the Wayland app_id
# and the prefix of the polkit action ids, so it must stay in sync with data/ and packaging/.
APP_ID = "io.github.elmodos.Kram"
POLKIT_HELPER_ACTION = f"{APP_ID}.helper"
HOMEPAGE = "https://github.com/elmodos/kram"
# where packaging/kram.spec installs kram/helper/kram_helper.py; data/*.policy points at this path
INSTALLED_HELPER = "/usr/libexec/kram-helper"
