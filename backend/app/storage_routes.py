from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from app.config import settings
from app.infrastructure.object_storage import LocalObjectStorage, get_object_storage


router = APIRouter(tags=["signed local storage"])


def _local_storage() -> LocalObjectStorage:
    storage = get_object_storage()
    if not isinstance(storage, LocalObjectStorage):
        raise HTTPException(status_code=404, detail="Local object storage is disabled")
    return storage


@router.put("/storage/uploads/{storage_key:path}", status_code=204, include_in_schema=False)
async def signed_local_upload(
    storage_key: str,
    request: Request,
    expires: int,
    content_type: str,
    byte_size: int,
    signature: str,
) -> Response:
    storage = _local_storage()
    if not storage.verify_upload(storage_key, expires, content_type, byte_size, signature):
        raise HTTPException(status_code=403, detail="Upload URL is invalid or expired")
    if byte_size < 1 or byte_size > settings.attachment_upload_max_bytes:
        raise HTTPException(status_code=413, detail="Upload is too large")
    if request.headers.get("content-type", "").split(";", 1)[0] != content_type:
        raise HTTPException(status_code=400, detail="Content-Type does not match signed upload")
    declared = request.headers.get("content-length")
    if declared is not None and int(declared) != byte_size:
        raise HTTPException(status_code=400, detail="Content-Length does not match signed upload")
    path = storage.path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".uploading")
    total = 0
    try:
        with temporary.open("wb") as handle:
            async for chunk in request.stream():
                total += len(chunk)
                if total > byte_size:
                    raise HTTPException(
                        status_code=400, detail="Uploaded size exceeds signed upload"
                    )
                handle.write(chunk)
        if total != byte_size:
            raise HTTPException(status_code=400, detail="Uploaded size does not match signed upload")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return Response(status_code=204)


@router.get("/storage/downloads/{storage_key:path}", include_in_schema=False)
def signed_local_download(
    storage_key: str,
    expires: int,
    filename: str,
    signature: str,
) -> FileResponse:
    storage = _local_storage()
    if not storage.verify_download(storage_key, expires, filename, signature):
        raise HTTPException(status_code=403, detail="Download URL is invalid or expired")
    path = storage.path(storage_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")
