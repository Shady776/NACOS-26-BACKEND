import logging
import os
import re
from typing import Optional
from urllib.parse import quote, unquote
from uuid import uuid4

import cloudinary
import cloudinary.uploader
import cloudinary.utils
import requests
from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

from app.config import CONFIG

logger = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=CONFIG.CLOUDINARY_CLOUD_NAME,
    api_key=CONFIG.CLOUDINARY_API_KEY,
    api_secret=CONFIG.CLOUDINARY_API_SECRET,
)

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain",
    "zip": "application/zip",
    "rar": "application/x-rar-compressed",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

# Cloudinary URLs look like:
#   https://res.cloudinary.com/<cloud>/raw/authenticated/v123/<folder>/<id>.pdf   (new, private)
#   https://res.cloudinary.com/<cloud>/raw/upload/v123/<folder>/<id>.pdf          (old, public)
#   https://res.cloudinary.com/<cloud>/image/upload/v123/<folder>/<id>.pdf        (old, public)
_CLOUDINARY_URL = re.compile(
    r"/(image|raw|video)/(upload|authenticated)/(?:s--[\w-]+--/)?(?:v(\d+)/)?(.+)$"
)
_EXTENSION = re.compile(r"[a-z][a-z0-9]{0,7}")


def parse_cloudinary_url(file_url: str) -> dict:
    """Returns resource_type, delivery_type, version, public_id and extension. Raises RuntimeError."""
    match = _CLOUDINARY_URL.search(file_url or "")
    if not match:
        raise RuntimeError(f"Unrecognised Cloudinary URL: {file_url}")

    resource_type, delivery_type, version, path = match.groups()
    path = unquote(path)
    root, dot_extension = os.path.splitext(path)
    extension = dot_extension.lstrip(".").lower()
    if not _EXTENSION.fullmatch(extension):
        extension = ""  # e.g. the ".123456" part of an old timestamp-based id

    # Raw files keep their extension inside the public_id; image/video files do not.
    if resource_type == "raw" or not extension:
        public_id = path
    else:
        public_id = root

    return {
        "resource_type": resource_type,
        "delivery_type": delivery_type,
        "version": version,
        "public_id": public_id,
        "extension": extension,
    }


def stored_file_extension(file_url: str) -> str:
    """File extension of a stored file ('' if it can't be worked out)."""
    try:
        return parse_cloudinary_url(file_url)["extension"]
    except RuntimeError:
        return ""


def media_type_for_extension(extension: Optional[str]) -> str:
    return MEDIA_TYPES.get((extension or "").lower(), "application/octet-stream")


def upload_private_file(fileobj, folder: str, extension: str) -> dict:
    """Upload as a private raw file. Returns Cloudinary's result (secure_url, bytes, ...)."""
    return cloudinary.uploader.upload(
        fileobj,
        folder=folder,
        public_id=f"{uuid4().hex}.{extension}",
        resource_type="raw",
        type="authenticated",
        overwrite=False,
    )


def build_download_url(file_url: str) -> str:
    """
    URL the server uses to fetch a file. Private files get a signed URL that only
    the server ever sees; older public files are fetched from their stored URL.
    """
    info = parse_cloudinary_url(file_url)
    if info["delivery_type"] == "upload":
        return file_url

    options = {
        "resource_type": info["resource_type"],
        "type": "authenticated",
        "sign_url": True,
        "secure": True,
    }
    if info["version"]:
        options["version"] = info["version"]
    if info["resource_type"] != "raw" and info["extension"]:
        options["format"] = info["extension"]

    url, _ = cloudinary.utils.cloudinary_url(info["public_id"], **options)
    return url


def delete_stored_file(file_url: str) -> None:
    """Raises if the file could not be removed. 'not found' counts as success."""
    info = parse_cloudinary_url(file_url)
    result = cloudinary.uploader.destroy(
        info["public_id"],
        resource_type=info["resource_type"],
        type=info["delivery_type"],
        invalidate=True,
    )
    if result.get("result") not in ("ok", "not found"):
        raise RuntimeError(f"Cloudinary refused to delete {info['public_id']}: {result}")


def content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def fetch_stored_file_bytes(file_url: str, max_bytes: int = 50 * 1024 * 1024) -> bytes:
    """Blocking download of a whole file (call it with run_in_threadpool from async code)."""
    response = requests.get(build_download_url(file_url), stream=True, timeout=(10, 60))
    try:
        if response.status_code != 200:
            raise RuntimeError(f"Storage returned status {response.status_code}")
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError("File is too large to read")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


def stream_stored_file(file_url: str, filename: str, media_type: Optional[str] = None) -> StreamingResponse:
    """
    Stream a stored file to the user as a download. Call it from a plain `def`
    route so the blocking requests call runs in a thread pool.
    """
    try:
        source_url = build_download_url(file_url)
    except RuntimeError:
        logger.exception("Bad storage URL: %s", file_url)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="This file's storage link is invalid",
        )

    try:
        response = requests.get(source_url, stream=True, timeout=(10, 60))
    except requests.Timeout:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Request to storage timed out",
        )
    except requests.RequestException:
        logger.exception("Could not reach storage for %s", file_url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch the file from storage",
        )

    if response.status_code != 200:
        response.close()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch the file from storage (status {response.status_code})",
        )

    headers = {
        "Content-Disposition": content_disposition(filename),
        "Cache-Control": "private, no-store",
    }
    if response.headers.get("Content-Length"):
        headers["Content-Length"] = response.headers["Content-Length"]

    def iterfile():
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        finally:
            response.close()

    return StreamingResponse(
        iterfile(),
        media_type=media_type or "application/octet-stream",
        headers=headers,
    )