from datetime import datetime, timezone
import json
import os
import threading
from pathlib import Path

from experiments.import_retention import audit_backups, preview_lock, prune_previews, prune_backups


def _preview(scene, token, created, saved=False):
    path = scene.parent/".import-previews"/scene.name/token
    path.mkdir(parents=True)
    (path/"summary.json").write_text(json.dumps({"created_at":datetime.fromtimestamp(created,timezone.utc).isoformat(),"saved":saved}))
    (path/"large.npy").write_bytes(b"candidate")
    return path


def test_preview_ttl_preserves_recent_active_and_legacy_receipts(tmp_path):
    scene = tmp_path/"demo"
    old = _preview(scene,"old",0)
    recent = _preview(scene,"recent",100000)
    active = _preview(scene,"active",0)
    legacy = _preview(scene,"legacy",0)
    (legacy/"summary.json").write_text('{"saved":true}')
    ready, release = threading.Event(), threading.Event()
    def owner():
        with preview_lock(scene,"active"):
            ready.set()
            release.wait(5)
    thread = threading.Thread(target=owner)
    thread.start()
    try:
        assert ready.wait(2)
        assert prune_previews(scene,now=100001) == ["old"]
        assert not old.exists() and recent.exists() and active.exists() and legacy.exists()
    finally:
        release.set()
        thread.join(5)


def test_saved_preview_keeps_only_the_receipt(tmp_path):
    scene = tmp_path/"demo"
    saved = _preview(scene,"saved",100000,True)
    prune_previews(scene,now=100001)
    assert [p.name for p in saved.iterdir()] == ["summary.json"]


def test_chinese_cad_receipt_uses_utf8_under_windows_locale(tmp_path, monkeypatch):
    scene = tmp_path / "demo"
    recent = _preview(scene, "recent", 100000)
    receipt = recent / "summary.json"
    record = json.loads(receipt.read_text(encoding="utf-8"))
    record["layer_name"] = "苍南分乡镇"
    receipt.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    read_text = Path.read_text

    def windows_read_text(path, encoding=None, errors=None):
        return read_text(path, encoding=encoding or "gbk", errors=errors)

    monkeypatch.setattr(Path, "read_text", windows_read_text)
    assert prune_previews(scene, now=100001) == []
    assert (recent / "large.npy").is_file()


def test_backups_prune_only_verified_success_and_protect_recovery(tmp_path):
    scene = tmp_path/"scene"
    scene.mkdir()
    root = tmp_path/"backups"
    for i in range(9):
        path = root/str(i)
        path.mkdir(parents=True)
        (path/"publication.json").write_text(json.dumps({"scene_id":scene.name,"status":"succeeded","completed_at":str(i)}))
    (root/"0"/".protected").touch()
    (scene/".roads-rebuilding").write_text(json.dumps({"backup":str(root/"1")}))
    (root/"unknown").mkdir()
    (root/"unknown"/"publication.json").write_text('{invalid-json')
    removed = prune_backups(root,scene)
    assert {os.path.basename(path) for path in removed} == {"2","3"}
    assert {p.name for p in root.iterdir()} == {"0","1","4","5","6","7","8","unknown"}
    assert not next(row for row in audit_backups(root,scene) if row["path"].endswith("unknown"))["verified_success"]
