"""
Shared validation for any route that accepts an UploadFile before it gets
forwarded to Cloudinary (or anywhere else). Without this, any authenticated
user can upload arbitrarily large or arbitrary-type files, which is a real
storage-cost / abuse risk once you have real users.

Usage:

    from ..utils.file_validation import validate_upload_file

    ALLOWED = {"pdf", "doc", "docx", "ppt", "pptx", "txt", "zip", "rar"}

    @router.post("/")
    async def upload(file: UploadFile = File(...), ...):
        validate_upload_file(file, allowed_extensions=ALLOWED)
        ...  # safe to upload now
"""

from fastapi import UploadFile, HTTPException, status

# 25MB default ceiling — adjust per route if some upload types genuinely
# need to be bigger (e.g. video) or smaller (e.g. profile pictures).
DEFAULT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024


def validate_upload_file(
    file: UploadFile,
    allowed_extensions: set[str],
    max_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> None:
    """
    Validates extension + size of an uploaded file.
    Raises HTTPException(400) if either check fails.
    Must be called BEFORE the file is sent to Cloudinary / read elsewhere —
    it rewinds the file pointer back to 0 when done, so the caller can
    still read/upload it normally afterward.
    """
    if not file.filename or "." not in file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a valid extension"
        )

    extension = file.filename.rsplit(".", 1)[-1].lower()
    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed types: {', '.join(sorted(allowed_extensions))}"
        )

    # UploadFile wraps a SpooledTemporaryFile — seek to the end to find its
    # size, then rewind so the rest of the route can still read it from 0.
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)

    if size > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {max_size_bytes // (1024 * 1024)}MB"
        )

    if size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty"
        )