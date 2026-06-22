# Copyright (c) Opendatalab. All rights reserved.
"""Storage-agnostic fetching of submitted file links into the local uploads dir.

A single ``fsspec.open(url, "rb")`` call resolves the right backend from the URL
scheme (``s3://`` via s3fs, ``gs://``/``gcs://`` via gcsfs, ``az://`` via adlfs,
``http(s)://`` incl. presigned object-store URLs, ``file://`` locally). The fetched
bytes are written into the same per-task ``uploads/`` directory that multipart
uploads use, so everything downstream of :class:`StoredUpload` is unchanged.

Eeach fsspec backend uses its standard env based auth (AWS credential chain for
s3fs, Application Default Credentials / Workload Identity for gcsfs, etc.).
"""

import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException

from mineru.utils.guess_suffix_or_lang import guess_suffix_by_bytes


def _load_fsspec():
    """Lazy-import fsspec so the base install stays slim (mirrors data/io/s3.py)."""
    try:
        import fsspec
    except ImportError as exc:
        raise ModuleNotFoundError(
            "Fetching file_urls requires optional dependencies. Install them with "
            "`pip install 'mineru[remote]'` (and `mineru[remote-s3]` / "
            "`mineru[remote-gcs]` for s3://, gs:// links)."
        ) from exc
    return fsspec


def _filename_from_url(url: str) -> str:
    """Derive a candidate filename from the URL path component, if any."""
    path = urlsplit(url).path
    name = Path(unquote(path)).name if path else ""
    return name


def fetch_url_to_dir(url: str, upload_dir: str):
    """Fetch ``url`` via fsspec and store it under ``upload_dir``.

    Returns a ``StoredUpload`` describing the local copy. Raises ``HTTPException``
    with a clean status code on unsupported schemes, missing backends, fetch
    failures, or unsupported file types.
    """
    # Imported here (not at module load) to avoid a circular import: fast_api imports
    # this module, and StoredUpload + the upload helpers live in fast_api.
    from mineru.cli.fast_api import SUPPORTED_UPLOAD_SUFFIXES, StoredUpload, build_upload_destination, cleanup_file
    from mineru.cli.common import normalize_task_stem, normalize_upload_filename

    if not url or not url.strip():
        raise HTTPException(status_code=400, detail="Empty file_urls entry")
    url = url.strip()

    fsspec = _load_fsspec()

    try:
        with fsspec.open(url, "rb") as handle:
            data = handle.read()
    except ImportError as exc:
        # fsspec raises ImportError when the scheme's backend (s3fs/gcsfs/...) is absent.
        raise HTTPException(
            status_code=400,
            detail=(
                f"No fsspec backend available for URL '{url}'. Install the matching "
                "extra, e.g. `pip install 'mineru[remote-s3]'` or "
                "`pip install 'mineru[remote-gcs]'`."
            ),
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"File not found: {url}") from exc
    except ValueError as exc:
        # Unknown protocol / malformed URL.
        raise HTTPException(status_code=400, detail=f"Invalid file_urls entry '{url}': {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch '{url}': {exc}") from exc

    raw_name = _filename_from_url(url)
    if raw_name:
        filename = normalize_upload_filename(raw_name)
    else:
        # No usable name in the URL (e.g. a presigned URL ending in a token): infer the
        # suffix from the bytes so suffix validation and downstream parsing still work.
        suffix = guess_suffix_by_bytes(data, Path("download"))
        filename = normalize_upload_filename(f"download-{uuid.uuid4()}.{suffix}")

    normalized_stem = normalize_task_stem(Path(filename).stem)
    destination = build_upload_destination(upload_dir, filename)

    try:
        with open(destination, "wb") as out:
            out.write(data)

        from mineru.utils.guess_suffix_or_lang import guess_suffix_by_path

        file_suffix = guess_suffix_by_path(destination)
        if file_suffix not in SUPPORTED_UPLOAD_SUFFIXES:
            cleanup_file(str(destination))
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_suffix}")
    except HTTPException:
        raise
    except Exception:
        cleanup_file(str(destination))
        raise

    return StoredUpload(
        original_name=url,
        stem=normalized_stem,
        path=str(destination),
    )
