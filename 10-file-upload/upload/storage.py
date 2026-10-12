"""File storage on the local filesystem with content-addressable naming.

Files are stored under ``storage/files/{hash[:2]}/{hash}`` so equal content
collides to a single on-disk location (deduplication for free) and the
directory tree stays shallow. Hashing uses BLAKE2b streamed over the bytes so
very large uploads never need to be held fully in memory.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import aiofiles

from upload.config import settings


def _storage_root() -> Path:
    root = settings.storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def hash_bytes(data: bytes) -> str:
    """Return the BLAKE2b hex digest of ``data``."""
    return hashlib.blake2b(data).hexdigest()


def _hex_stream_partial(fileobj, chunk_size: int = 64 * 1024) -> str:
    """Stream a file-like object into a fresh ``hashlib`` digest."""
    h = hashlib.blake2b()
    while True:
        chunk = fileobj.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()


def _path_for_hash(hash_: str) -> Path:
    root = _storage_root()
    return root / "files" / hash_[:2] / hash_


def exists(hash_: str) -> bool:
    """Whether a file with the given ``hash_`` is already stored."""
    return _path_for_hash(hash_).is_file()


def get_path(hash_: str) -> Path:
    """Return the on-disk :class:`Path` for ``hash_``, if it exists."""
    path = _path_for_hash(hash_)
    if not path.is_file():
        raise FileNotFoundError(f"no stored file for hash {hash_}")
    return path


async def save_file(data: bytes) -> str:
    """Persist ``data`` content-addressably and return its hash.

    Returns:
        The BLAKE2b hex digest naming the file.
    """
    hash_ = hash_bytes(data)
    path = _path_for_hash(hash_)
    if path.is_file():
        return hash_  # already stored, deduplicated
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "wb") as fh:
        await fh.write(data)
    return hash_


async def save_stream(iterable, *, chunk_size: int = 64 * 1024) -> str:
    """Write a streamed (async) iterator to disk while hashing on the fly.

    Files are written to a temporary sibling path first so a partial upload
    never masquerades as a complete file; the temp file is renamed into place
    on success.

    Args:
        iterable: An async iterable of ``bytes`` chunks (e.g. UploadFile).
        chunk_size: Bytes read per iteration.

    Returns:
        The BLAKE2b hex digest of the full stream.
    """
    h = hashlib.blake2b()
    root = _storage_root() / "files"
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (hashlib.blake2b(b"tmp").hexdigest()[:16] + ".part")
    try:
        async with aiofiles.open(tmp, "wb") as fh:
            async for chunk in iterable:
                h.update(chunk)
                await fh.write(chunk)
        hash_ = h.hexdigest()
        final = _path_for_hash(hash_)
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.is_file():
            # Same content already stored (dedup) — discard our temp write.
            tmp.unlink(missing_ok=True)
            return hash_
        os.replace(tmp, final)
        return hash_
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def delete_file(hash_: str) -> bool:
    """Remove the stored file for ``hash_``.

    Returns:
        ``True`` if a file was deleted, ``False`` if it did not exist.
    """
    path = _path_for_hash(hash_)
    if not path.is_file():
        return False
    path.unlink()
    return True