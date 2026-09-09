"""CI sets LIBNFS_LIBRARY after building the platform's native library."""
import os
import pytest


@pytest.mark.skipif(not os.environ.get('LIBNFS_LIBRARY'), reason='Set LIBNFS_LIBRARY to test native ABI')
def test_native_context_loads():
    from remote_fs_browser.nfs import library
    lib = library()
    context = lib.nfs_init_context()
    assert context
    lib.nfs_destroy_context(context)
