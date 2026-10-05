"""Entry point for the packed app (PyInstaller builds SinhalaSubs.exe from this file)."""

import sys


def _log_to_file() -> None:
    """A window app has no console: send prints and errors to %APPDATA%\\SinhalaSubs\\sinhalasubs.log."""
    if sys.stdout is not None:
        return
    from sinhalasubs.config import app_data_dir
    log = open(app_data_dir() / "sinhalasubs.log", "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log


if __name__ == "__main__":
    _log_to_file()
    if "--selftest" in sys.argv:
        from sinhalasubs.selftest import run
        sys.exit(run())
    from sinhalasubs.__main__ import main
    main()
