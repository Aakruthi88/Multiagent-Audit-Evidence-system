import hashlib
from pathlib import Path
from typing import Tuple
from fastapi import UploadFile
from app.core.config import settings

class StorageService:
    @staticmethod
    def save_bundle_file(bundle_id: str, doc_type: str, file: UploadFile) -> Tuple[str, str]:
        """
        Saves uploaded file to STORAGE_DIR/bundles/{bundle_id}/{doc_type}_{filename}
        Returns: (file_path, sha256_hash)
        """
        bundle_dir = settings.STORAGE_DIR / "bundles" / str(bundle_id)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = bundle_dir / f"{doc_type}_{file.filename}"
        
        sha256_hash = hashlib.sha256()
        
        file.file.seek(0)
        with open(target_path, "wb") as f:
            while chunk := file.file.read(8192):
                sha256_hash.update(chunk)
                f.write(chunk)
        file.file.seek(0)
        
        return str(target_path.resolve()), sha256_hash.hexdigest()

storage_service = StorageService()
