"""
Storage provider protocol (Strategy Pattern – OCP / ISP).

Any new storage backend (S3, GCS, Azure Blob) only needs to implement
this protocol. Existing code is never modified.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageProvider(Protocol):
    async def save(self, file_bytes: bytes, filename: str) -> str:
        """Persist *file_bytes* and return a URI / path to the stored object."""
        ...

    async def delete(self, path: str) -> None:
        """Remove the object at *path*. Silently succeeds if already gone."""
        ...
