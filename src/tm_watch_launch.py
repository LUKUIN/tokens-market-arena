"""Start the preferred WPF front end and detect an immediate app-host failure."""

import os
from pathlib import Path
import subprocess


def start_wpf(root, api_url):
    """Return the viewer process and an optional fallback reason."""
    executable = (Path(root) / "viewer-cs/TokensWatch/bin/Release/net8.0-windows"
                  / "TokensWatch.exe")
    if (os.environ.get("TM_WATCH_IMPL", "").strip().lower() in {"py", "tk", "tkinter"}
            or not executable.is_file()):
        return None, None

    # GUI app hosts normally display a modal dialog for a missing runtime.
    # Suppress it here so the host can exit and the calling launcher can open tkinter.
    env = dict(os.environ, TM_WATCH_API=api_url, DOTNET_DISABLE_GUI_ERRORS="1")
    try:
        process = subprocess.Popen([executable], cwd=root, env=env)
    except OSError as error:
        return None, str(error)
    try:
        exit_code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return process, None

    if exit_code != 0:
        return None, f"0x{exit_code & 0xffffffff:08X}"
    return process, None
