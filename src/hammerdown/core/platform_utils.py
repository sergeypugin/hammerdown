from __future__ import annotations

import os
import sys


def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")
