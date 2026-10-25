import subprocess
import sys

import pytest

from experiments.scene_lock import CoordinateSceneError, scene_write_lock


def test_kernel_lock_excludes_another_process_and_releases_after_crash(tmp_path):
    code = """
import sys
from pathlib import Path
from experiments.scene_lock import scene_write_lock
with scene_write_lock('demo', Path(sys.argv[1])):
    print('locked', flush=True)
    sys.stdin.read()
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(CoordinateSceneError):
            with scene_write_lock("demo", tmp_path):
                pass
        with scene_write_lock("other", tmp_path):
            pass
    finally:
        child.kill()
        child.wait(timeout=5)
    with scene_write_lock("demo", tmp_path):
        assert (tmp_path / ".locks/demo.lock").is_file()


def test_same_thread_can_read_inside_its_publication_transaction(tmp_path):
    with scene_write_lock("demo", tmp_path):
        with scene_write_lock("demo", tmp_path, blocking=True):
            pass
