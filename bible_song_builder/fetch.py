"""Download and cache every input at its pinned revision.

Files land in ``cache/`` (git-ignored) under a path that includes the revision, so changing
a pin in ``pins.json`` never serves a stale file. Nothing here parses data; see the other
modules for that.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import threading
import time
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
USER_AGENT = "bible-song-builder/0.1 (+https://github.com/bcv-commons/bible-song-builder)"


class NotFound(Exception):
    """The file does not exist at that revision (HTTP 404)."""


@lru_cache(maxsize=1)
def pins() -> dict:
    return json.loads((ROOT / "pins.json").read_text(encoding="utf-8"))


def _get(url: str, dest: Path, retries: int = 6) -> Path:
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            tmp = dest.with_suffix(f"{dest.suffix}.{os.getpid()}-{threading.get_ident()}.part")   # safe in parallel
            tmp.write_bytes(data)
            tmp.replace(dest)
            return dest
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(url) from None
            if attempt == retries - 1:
                raise
        except (OSError, http.client.HTTPException):    # URLError, timeouts, connection resets, short reads
            if attempt == retries - 1:
                raise
        time.sleep(min(60, 3 * 2 ** attempt))
    raise RuntimeError("unreachable")


def hf(dataset: str, path: str) -> Path:
    """A file of a pinned Hugging Face dataset (key of pins.json "huggingface")."""
    pin = pins()["huggingface"][dataset]
    rev = pin["revision"]
    url = f"https://huggingface.co/datasets/{pin['repo']}/resolve/{rev}/{urllib.parse.quote(path)}"
    return _get(url, CACHE / "hf" / dataset / rev[:12] / path)


def hf_json(dataset: str, path: str):
    return json.loads(hf(dataset, path).read_text(encoding="utf-8"))


def release_dir(name: str) -> Path:
    """A pinned GitHub release asset (key of pins.json "releases"), a zip checked against its
    sha256 and unpacked into cache/. Returns the folder it was unpacked into."""
    pin = pins()["releases"][name]
    base = CACHE / "releases" / name / pin["tag"]
    done = base / ".unpacked"
    if done.exists():
        return base
    url = f"https://github.com/{pin['repo']}/releases/download/{pin['tag']}/{pin['asset']}"
    z = _get(url, base.parent / f"{pin['tag']}-{pin['asset']}")
    digest = hashlib.sha256(z.read_bytes()).hexdigest()
    if digest != pin["sha256"]:
        z.unlink()
        raise RuntimeError(f"{url}: sha256 {digest} is not the pinned {pin['sha256']} (pins.json releases.{name}); "
                           "the release asset was replaced, check it and update the pin")
    with zipfile.ZipFile(z) as zf:
        for m in zf.namelist():          # only plain files directly or below base, no absolute or ../ paths
            if m.startswith("/") or ".." in Path(m).parts:
                raise RuntimeError(f"{url}: unsafe path in zip: {m}")
        zf.extractall(base)
    done.write_text(pin["sha256"], encoding="utf-8")
    return base
