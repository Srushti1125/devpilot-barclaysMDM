"""
Local-disk implementation of the StorageProvider protocol.
"""

import uuid
from pathlib import Path


class LocalDiskStorage:
    """Saves files to a local directory. Used in development and Docker-compose setups."""

    def __init__(self, upload_dir: str):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, file_bytes: bytes, filename: str) -> str:
        import asyncio
        suffix = Path(filename).suffix.lower()
        target = self.upload_dir / f"{uuid.uuid4()}{suffix}"
        await asyncio.to_thread(target.write_bytes, file_bytes)
        return str(target.resolve())

    async def delete(self, path: str) -> None:
        import asyncio
        target = Path(path)
        await asyncio.to_thread(target.unlink, missing_ok=True)
