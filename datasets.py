"""Discover tabular files in data/ and load web uploads without code edits."""

import os
import tempfile
import threading
from contextvars import ContextVar
from pathlib import Path

import storage
from tools import DATASET, SUPPORTED_EXTENSIONS, _CON, _CON_LOCK, dataset_name, load_data, start_analysis_context

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
_lock = threading.RLock()
_loaded = {}
_errors = {}
_guest_loaded = ContextVar("byte_loaded_datasets", default=None)
_guest_errors = ContextVar("byte_dataset_errors", default=None)


def _state():
    if storage.owner_id() == "local":
        return _loaded, _errors
    loaded, errors = _guest_loaded.get(), _guest_errors.get()
    return loaded if loaded is not None else {}, errors if errors is not None else {}


def _unique_name(filename, taken):
    base = dataset_name(filename)
    name, number = base, 2
    while name in taken:
        name, number = f"{base}_{number}", number + 1
    return name


def _remove(name):
    with _CON_LOCK:
        DATASET.pop(name, None)
        try:
            _CON.unregister(name)
        except Exception:
            pass


def _load_upload(upload):
    suffix = Path(upload["filename"]).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(bytes(upload["content"]))
        path = tmp.name
    try:
        load_data(path, upload["name"])
    finally:
        os.unlink(path)


def sync():
    """Called before listing or analyzing so newly dropped files appear immediately."""
    with _lock:
        if storage.owner_id() != "local":
            start_analysis_context()
            _guest_loaded.set({})
            _guest_errors.set({})
        loaded, errors = _state()
        storage.init()
        DATA_DIR.mkdir(exist_ok=True)
        files = sorted((p for p in DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and not p.name.startswith("~$")), key=lambda p: p.name.lower())
        uploads = storage.list_uploads()
        desired = {}
        taken = {u["name"] for u in uploads}
        for path in files:
            name = _unique_name(path.name, taken)
            taken.add(name)
            desired[f"file:{path}"] = (name, (path.stat().st_mtime_ns, path.stat().st_size), path)
        for upload in uploads:
            desired[f"upload:{upload['id']}"] = (upload["name"], upload["id"], upload)
        for key, (name, version, source) in desired.items():
            if loaded.get(key) == (name, version):
                continue
            if key in loaded:
                _remove(loaded[key][0])
            try:
                if key.startswith("file:"):
                    load_data(str(source), name)
                else:
                    full = storage.get_upload(source["id"])
                    _load_upload(full)
                loaded[key] = (name, version)
                errors.pop(key, None)
            except Exception as exc:
                errors[key] = str(exc)
        for key in list(loaded):
            if key not in desired:
                _remove(loaded.pop(key)[0])
        return list_datasets(should_sync=False)


def list_datasets(should_sync=True):
    if should_sync:
        sync()
    with _lock:
        loaded, errors = _state()
        items = []
        for key, (name, _) in loaded.items():
            df = DATASET.get(name)
            if df is not None:
                items.append({"id": key, "name": name, "filename": Path(key[5:]).name if key.startswith("file:") else next((u["filename"] for u in storage.list_uploads() if key == f"upload:{u['id']}"), name), "rows": len(df), "columns": len(df.columns), "source": "folder" if key.startswith("file:") else "upload"})
        return {"datasets": sorted(items, key=lambda x: x["name"]), "errors": errors.copy()}


def upload(filename, content):
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type. Use: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    if not content:
        raise ValueError("The file is empty")
    with _lock:
        sync()
        name = _unique_name(filename, set(DATASET))
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            path = tmp.name
        try:
            load_data(path, name)
        except Exception:
            _remove(name)
            raise
        finally:
            os.unlink(path)
        try:
            item = storage.save_upload(name, Path(filename).name, content)
        except Exception:
            _remove(name)
            raise
        loaded, _ = _state()
        loaded[f"upload:{item['id']}"] = (name, item["id"])
        return {**item, "rows": len(DATASET[name]), "columns": len(DATASET[name].columns), "source": "upload"}


def delete(upload_id):
    with _lock:
        sync()
        loaded, _ = _state()
        _remove(loaded.pop(f"upload:{upload_id}", ("",))[0])
        return storage.delete_upload(upload_id)
