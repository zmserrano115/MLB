from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Protocol


class ArtifactConflictError(RuntimeError):
    """Raised when an immutable artifact name already has different content."""


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    uri: str
    sha256: str
    size_bytes: int
    generation: str | None = None


class ArtifactStore(Protocol):
    def put_bytes(
        self,
        *,
        source: str,
        generation: str,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredArtifact: ...


def _safe_parts(*values: str) -> tuple[str, ...]:
    parts: list[str] = []
    for value in values:
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or not candidate.parts:
            raise ValueError("artifact path must be relative")
        if any(part in {"", ".", ".."} for part in candidate.parts):
            raise ValueError("artifact path contains an unsafe segment")
        parts.extend(candidate.parts)
    return tuple(parts)


class LocalArtifactStore:
    """Immutable local implementation used by tests and Compose shadow runs."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def put_bytes(
        self,
        *,
        source: str,
        generation: str,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredArtifact:
        del content_type
        target = self._root.joinpath(*_safe_parts(source, generation, name))
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256(data).hexdigest()
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError as exc:
            existing = target.read_bytes()
            if sha256(existing).hexdigest() != digest:
                raise ArtifactConflictError(f"immutable artifact conflict: {target.name}") from exc
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        return StoredArtifact(target.as_uri(), digest, len(data))


class GcsArtifactStore:
    """GCS implementation using generation-match zero to prevent overwrites."""

    def __init__(self, bucket: Any) -> None:
        self._bucket = bucket

    @classmethod
    def from_bucket_name(cls, bucket_name: str) -> GcsArtifactStore:
        if not bucket_name:
            raise ValueError("GCS_BUCKET is required when ARTIFACT_STORE=gcs")
        from google.cloud import storage

        return cls(storage.Client().bucket(bucket_name))

    def put_bytes(
        self,
        *,
        source: str,
        generation: str,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredArtifact:
        object_name = "/".join(_safe_parts(source, generation, name))
        blob = self._bucket.blob(object_name)
        digest = sha256(data).hexdigest()
        blob.metadata = {"sha256": digest}
        try:
            blob.upload_from_string(
                data,
                content_type=content_type,
                if_generation_match=0,
                checksum="crc32c",
            )
        except Exception as exc:
            # A precondition failure can be an idempotent replay. Reload metadata to prove it.
            try:
                blob.reload()
            except Exception:
                raise exc from None
            if (blob.metadata or {}).get("sha256") != digest or int(blob.size) != len(data):
                raise ArtifactConflictError(
                    f"immutable GCS artifact conflict: {object_name}"
                ) from exc
        return StoredArtifact(
            uri=f"gs://{self._bucket.name}/{object_name}",
            sha256=digest,
            size_bytes=len(data),
            generation=str(blob.generation) if blob.generation is not None else None,
        )
