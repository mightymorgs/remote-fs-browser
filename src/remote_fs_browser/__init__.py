"""Cross-platform remote filesystem browsing."""
from importlib.metadata import PackageNotFoundError, version
from .policy import Policy
from .sessions import Browser, FilesystemSession

try:
    __version__ = version('remote-fs-browser')
except PackageNotFoundError:
    __version__ = '0.0.0'

__all__ = ['Browser', 'FilesystemSession', 'Policy', '__version__']
