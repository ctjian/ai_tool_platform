"""Filesystem layout helpers for arxiv translate jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
import json


@dataclass(frozen=True)
class JobPaths:
    base_dir: Path
    job_root: Path
    source_dir: Path
    source_archive: Path
    extract_dir: Path
    work_dir: Path
    translated_dir: Path
    output_dir: Path
    job_json: Path


def build_job_paths(base_dir: str | Path, arxiv_id: str, job_id: str) -> JobPaths:
    root = Path(base_dir)
    job_root = root / arxiv_id / job_id
    return JobPaths(
        base_dir=root,
        job_root=job_root,
        source_dir=job_root / "source",
        source_archive=job_root / "source" / "source.tar",
        extract_dir=job_root / "source" / "extract",
        work_dir=job_root / "work",
        translated_dir=job_root / "work" / "translated",
        output_dir=job_root / "output",
        job_json=job_root / "job.json",
    )


def ensure_job_dirs(paths: JobPaths) -> None:
    for p in [
        paths.job_root,
        paths.source_dir,
        paths.extract_dir,
        paths.work_dir,
        paths.translated_dir,
        paths.output_dir,
    ]:
        p.mkdir(parents=True, exist_ok=True)


def save_job_json(paths: JobPaths, payload: Dict[str, Any]) -> None:
    paths.job_json.parent.mkdir(parents=True, exist_ok=True)
    paths.job_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def artifact_payload(*, file_path: Path, paths: JobPaths, static_prefix: str) -> Dict[str, Any]:
    rel = file_path.resolve().relative_to(paths.base_dir.resolve())
    return {
        "name": file_path.name,
        "path": str(file_path),
        "url": f"{static_prefix}/{rel.as_posix()}",
        "size_bytes": file_path.stat().st_size if file_path.exists() else 0,
    }
