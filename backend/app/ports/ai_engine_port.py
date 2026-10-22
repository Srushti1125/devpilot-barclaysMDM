from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class AIEnginePort(ABC):
    @abstractmethod
    async def generate(self, project_id: str, artifact_type: str, requirement_text: str) -> dict: ...

    @abstractmethod
    async def ingest(self, file_path: str, project_id: str, doc_type: str,
                     doc_id: str | None = None) -> dict: ...

    @abstractmethod
    async def ingest_status(self, engine_job_id: str) -> dict: ...

    @abstractmethod
    async def artifact_types(self) -> dict: ...

    @abstractmethod
    async def stream_generate(self, project_id: str, artifact_type: str,
                              requirement_text: str) -> AsyncIterator[bytes]: ...

    @abstractmethod
    async def generate_compare(self, project_id: str, artifact_type: str,
                               requirement_text: str) -> dict: ...

    @abstractmethod
    async def evaluate_batch(self, project_id: str | None = None,
                             retrieval_mode: str = "vector") -> dict: ...
