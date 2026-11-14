"""Open the desktop file chooser for the local Blueprint server."""
import os
from pathlib import Path
import shutil
import subprocess

from .documents import DocumentError


def available():
    return bool((os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")) and shutil.which("zenity"))


def pick_file():
    executable = shutil.which("zenity")
    if not executable or not available():
        raise DocumentError("The desktop file picker is unavailable.", 503)
    try:
        result = subprocess.run(
            [executable, "--file-selection", "--title=Choose a blueprint",
             "--file-filter=Blueprint files | *.jpg *.jpeg *.png *.pdf *.svg *.dxf *.dwg *.ifc"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=300, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DocumentError("The desktop file picker could not open or timed out.", 503) from None
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise DocumentError("The desktop file picker could not select a file.", 503)
    path = Path(os.fsdecode(result.stdout.removesuffix(b"\n")))
    if not path.is_absolute() or not path.is_file():
        raise DocumentError("Choose a regular file from the desktop picker.", 422)
    return path
