"""`python -m remote_fs_browser` and frozen builds enter here."""
import multiprocessing

from .cli import main

if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
