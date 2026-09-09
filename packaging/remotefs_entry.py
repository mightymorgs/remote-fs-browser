"""PyInstaller entry point for the frozen ``remotefs`` executable.

``freeze_support`` must run before anything else so that child processes
spawned by ``multiprocessing`` inside a frozen Windows build re-enter here
instead of re-running the CLI.
"""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from remote_fs_browser.cli import main

    main()
