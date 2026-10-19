"""Software archaeology engine: evidence first, AI second."""

from .evidence import EvidenceItem, EvidenceReference, extract_evidence, extract_from_text
from .fetcher import ALLOWED_GIT_HOSTS, RepoMirror, TagInfo, fetch_repo
from .inference import infer_genome
from .pypi_client import PackageNotFound, PypiClient, Release
from .timeline import Snapshot, Timeline, build_timeline, discover_watched_paths

__all__ = [
    "ALLOWED_GIT_HOSTS",
    "EvidenceItem",
    "EvidenceReference",
    "PackageNotFound",
    "PypiClient",
    "Release",
    "RepoMirror",
    "Snapshot",
    "TagInfo",
    "Timeline",
    "build_timeline",
    "discover_watched_paths",
    "extract_evidence",
    "extract_from_text",
    "fetch_repo",
    "infer_genome",
]
