import hashlib
import re
from pathlib import Path
from typing import Tuple
from fastapi import HTTPException, UploadFile, status
from app.core.config import settings

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25MB limit


class StorageService:
    @staticmethod
    def save_bundle_file(bundle_id: str, doc_type: str, file: UploadFile) -> Tuple[str, str]:
        """
        Saves uploaded file to STORAGE_DIR/bundles/{bundle_id}/{doc_type}_{safe_filename}
        Enforces path traversal protection, file type validation, and file size limits.
        Returns: (file_path, sha256_hash)
        """
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file must have a filename."
            )

        # 1. Sanitize filename and prevent path traversal
        raw_name = Path(file.filename).name
        if ".." in raw_name or "/" in raw_name or "\\" in raw_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid filename: path traversal characters detected."
            )

        safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', raw_name)
        if not safe_name.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type for '{safe_name}'. Only PDF documents are allowed."
            )

        bundle_dir = (settings.STORAGE_DIR / "bundles" / str(bundle_id)).resolve()
        bundle_dir.mkdir(parents=True, exist_ok=True)

        target_path = (bundle_dir / f"{doc_type}_{safe_name}").resolve()

        # Strict containment verification
        if not str(target_path).startswith(str(bundle_dir)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security violation: Target file path escapes bundle directory."
            )

        sha256_hash = hashlib.sha256()
        total_bytes = 0

        file.file.seek(0)
        with open(target_path, "wb") as f:
            while chunk := file.file.read(8192):
                total_bytes += len(chunk)
                if total_bytes > MAX_FILE_SIZE_BYTES:
                    # Clean up oversized file
                    f.close()
                    if target_path.exists():
                        target_path.unlink()
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB."
                    )
                sha256_hash.update(chunk)
                f.write(chunk)
        file.file.seek(0)

        return str(target_path), sha256_hash.hexdigest()


storage_service = StorageService()
