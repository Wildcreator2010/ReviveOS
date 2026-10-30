"""Build the ReviveOS submission archive with a manifest and SHA-256 checksums.

Run from the repository root:
    python tools/build_submission_zip.py

The archive is written beside the repository so it never becomes an untracked
file inside the source tree. Existing archives are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = ROOT.parent
PACKAGE_NAME = "ReviveOS-提交包-2026-10-30"
ARCHIVE_ROOT = "ReviveOS-提交包"

ROOT_FILES = [
    ".dockerignore",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    ".npmrc",
    ".pre-commit-config.yaml",
    ".python-version",
    "DELIVERY.md",
    "Dockerfile.api",
    "Dockerfile.web",
    "Dockerfile.worker",
    "Makefile",
    "README.md",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "uv.lock",
    "uv.toml",
]

SOURCE_DIRS = [
    ".github",
    "agents",
    "apps",
    "benchmarks",
    "cli",
    "docs",
    "infra",
    "packages",
    "revivebench",
    "schemas",
    "tests",
    "tools",
]

DOC_EXCLUDES = {
    Path("docs/tasks"),
    Path("docs/agents"),
    Path("docs/未完成任务提示词.md"),
}

SKIP_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pnpm-store",
    ".pytest-basetemp",
    ".pytest-cache",
    ".pytest-tmp",
    ".pytest-work",
    ".ruff_cache",
    ".scratch",
    ".uv-cache",
    ".uv-python",
    ".venv",
    "__pycache__",
    "artifacts",
    "dist",
    "htmlcov",
    "node_modules",
    "out",
    "release",
    "release-dir",
    "release-final",
    "release-final2",
    "release-final3",
    "release-final4",
    "release-nsis",
    "release-test",
}

SKIP_SUFFIXES = {
    ".coverage",
    ".log",
    ".pyc",
    ".pyo",
    ".revive",
    ".tsbuildinfo",
}

ARTIFACTS = [
    ("01-作品介绍/ReviveOS-作品介绍.pdf", ROOT / "docs/ReviveOS-作品介绍.pdf"),
    ("01-作品介绍/ReviveOS-作品介绍.html", ROOT / "docs/ReviveOS-作品介绍.html"),
    ("02-使用方案/ReviveOS-使用方案.pdf", ROOT / "docs/ReviveOS-使用方案.pdf"),
    ("02-使用方案/ReviveOS-使用方案.md", ROOT / "docs/ReviveOS-使用方案.md"),
    ("02-使用方案/ReviveOS-使用方案.html", ROOT / "docs/ReviveOS-使用方案.html"),
    ("03-演示视频/reviveos-film-4min.mp4", ROOT / "promo/out/reviveos-film-4min.mp4"),
    ("03-演示视频/可选-80秒宣传片.mp4", ROOT / "promo/out/reviveos-promo-1080p.mp4"),
    ("04-提交信息/ReviveOS-提交材料.md", ROOT / "docs/ReviveOS-提交材料.md"),
]


@dataclass
class Entry:
    archive: str
    source: Path | None
    data: bytes | None = None
    compress: bool = True


@dataclass
class Record:
    archive: str
    size: int
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_pages(path: Path) -> int:
    data = path.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page(?![s])", data))
    if pages:
        return pages
    counts = [int(value) for value in re.findall(rb"/Count\s+(\d+)", data)]
    return max(counts, default=0)


def mp4_info(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        header = handle.read(12)
    if len(header) < 12 or header[4:8] != b"ftyp":
        raise AssertionError(f"Not an MP4 file: {path}")

    def read_u32(handle, position: int) -> int:
        handle.seek(position)
        return int.from_bytes(handle.read(4), "big")

    def boxes(handle, start: int, end: int):
        position = start
        while position + 8 <= end:
            handle.seek(position)
            header = handle.read(8)
            size = int.from_bytes(header[:4], "big")
            kind = header[4:8]
            header_len = 8
            if size == 1:
                size = int.from_bytes(handle.read(8), "big")
                header_len = 16
            elif size == 0:
                size = end - position
            if size < header_len or position + size > end:
                break
            yield kind, position + header_len, position + size
            position += size

    def children(handle, start: int, end: int, kind: bytes):
        for child_kind, child_start, child_end in boxes(handle, start, end):
            if child_kind == kind:
                yield child_start, child_end

    duration = 0.0
    has_audio = False
    with path.open("rb") as handle:
        total = path.stat().st_size
        moov = next(children(handle, 0, total, b"moov"))
        timescales: dict[int, int] = {}
        for trak_start, trak_end in children(handle, *moov, b"trak"):
            tkhd_start, _ = next(children(handle, trak_start, trak_end, b"tkhd"))
            handle.seek(tkhd_start)
            version = handle.read(1)[0]
            track_id = read_u32(handle, tkhd_start + (12 if version == 0 else 20))
            mdia_start, mdia_end = next(children(handle, trak_start, trak_end, b"mdia"))
            mdhd_start, _ = next(children(handle, mdia_start, mdia_end, b"mdhd"))
            handle.seek(mdhd_start)
            version = handle.read(1)[0]
            timescale = read_u32(handle, mdhd_start + (12 if version == 0 else 20))
            timescales[track_id] = timescale
            for hdlr_start, _ in children(handle, mdia_start, mdia_end, b"hdlr"):
                handle.seek(hdlr_start)
                handle.read(8)
                if handle.read(4) == b"soun":
                    has_audio = True

        sample_durations: dict[int, int] = {}
        for moof_start, moof_end in children(handle, 0, total, b"moof"):
            for traf_start, traf_end in children(handle, moof_start, moof_end, b"traf"):
                tfhd_start, _ = next(children(handle, traf_start, traf_end, b"tfhd"))
                track_id = read_u32(handle, tfhd_start + 4)
                for trun_start, _trun_end in children(handle, traf_start, traf_end, b"trun"):
                    flags = read_u32(handle, trun_start) & 0xFFFFFF
                    count = read_u32(handle, trun_start + 4)
                    position = trun_start + 8
                    if flags & 0x1:
                        position += 4
                    if flags & 0x4:
                        position += 4
                    elapsed = 0
                    for _ in range(count):
                        sample_duration = None
                        if flags & 0x100:
                            sample_duration = read_u32(handle, position)
                            position += 4
                        if flags & 0x200:
                            position += 4
                        if flags & 0x400:
                            position += 4
                        if flags & 0x800:
                            position += 4
                        if sample_duration is not None:
                            elapsed += sample_duration
                    sample_durations[track_id] = sample_durations.get(track_id, 0) + elapsed
        if sample_durations:
            candidates = [
                elapsed / timescales[track_id]
                for track_id, elapsed in sample_durations.items()
                if timescales.get(track_id)
            ]
            duration = max(candidates, default=0.0)

        if duration == 0:
            mvhd_start, _ = next(children(handle, *moov, b"mvhd"))
            handle.seek(mvhd_start)
            version = handle.read(1)[0]
            handle.read(3)
            if version == 0:
                handle.read(8)
                timescale, raw_duration = struct.unpack(">II", handle.read(8))
            else:
                handle.read(16)
                timescale = struct.unpack(">I", handle.read(4))[0]
                raw_duration = struct.unpack(">Q", handle.read(8))[0]
            if timescale:
                duration = raw_duration / timescale

    return {"duration": round(duration, 3), "has_audio": has_audio}


def git_state() -> dict[str, object]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    changes = [line for line in run("status", "--porcelain").splitlines() if line]
    remotes = run("remote", "-v")
    repository_url = ""
    for line in remotes.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "origin" and fields[-1] == "(push)":
            repository_url = fields[1]
    return {
        "commit": run("rev-parse", "--short", "HEAD"),
        "dirty_entries": len(changes),
        "remote": remotes,
        "repository_url": repository_url,
    }


def should_skip(relative: Path) -> bool:
    if relative in DOC_EXCLUDES:
        return True
    if relative.suffix in SKIP_SUFFIXES:
        return True
    if relative.name == ".env":
        return True
    if relative.name.startswith(".tmp"):
        return True
    return False


def source_entries() -> list[Entry]:
    entries: list[Entry] = []
    for name in ROOT_FILES:
        path = ROOT / name
        assert path.is_file(), f"Missing source file: {path}"
        entries.append(Entry(f"05-源码/ReviveOS/{name}", path))

    for name in SOURCE_DIRS:
        base = ROOT / name
        assert base.is_dir(), f"Missing source directory: {base}"
        for directory, dirnames, filenames in os.walk(base):
            current = Path(directory)
            dirnames[:] = sorted(
                dirname
                for dirname in dirnames
                if dirname not in SKIP_DIR_NAMES
                and (current / dirname).relative_to(ROOT) not in DOC_EXCLUDES
                and (current / dirname).relative_to(ROOT) != Path("apps/desktop/web")
                and not dirname.startswith("pytest-cache-files-")
                and not dirname.endswith(".egg-info")
            )
            for filename in sorted(filenames):
                path = current / filename
                relative = path.relative_to(ROOT)
                if should_skip(relative):
                    continue
                entries.append(Entry(f"05-源码/ReviveOS/{relative.as_posix()}", path))
    return entries


def add_file(zf: zipfile.ZipFile, entry: Entry, records: list[Record]) -> None:
    assert entry.source is not None
    source = entry.source
    stat = source.stat()
    timestamp = time.localtime(stat.st_mtime)[:6]
    info = zipfile.ZipInfo(entry.archive, date_time=timestamp)
    info.compress_type = zipfile.ZIP_DEFLATED if entry.compress else zipfile.ZIP_STORED
    info.external_attr = (stat.st_mode & 0xFFFF) << 16
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, zf.open(info, "w") as writer:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            writer.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    assert size == stat.st_size, f"Short read: {source}"
    records.append(Record(entry.archive, size, digest.hexdigest()))


def add_bytes(zf: zipfile.ZipFile, entry: Entry, records: list[Record]) -> None:
    assert entry.data is not None
    info = zipfile.ZipInfo(entry.archive, date_time=(2026, 10, 30, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, entry.data)
    records.append(Record(entry.archive, len(entry.data), hashlib.sha256(entry.data).hexdigest()))


def build_manifest(
    pdf_pages_map: dict[str, int],
    video_info: dict[str, object],
    source_count: int,
    source_bytes: int,
    git: dict[str, object],
) -> str:
    repository_url = str(git.get("repository_url") or "")
    source_mib = source_bytes / 1024 / 1024
    if repository_url:
        repository_line = f"1. **公开代码仓库**：已推送至 {repository_url}；提交前用未登录浏览器复核可访问性。"
        remaining_links = "仅公开视频播放链接未勾选"
    else:
        repository_line = (
            "1. **公开代码仓库**：把 `05-源码/ReviveOS/` 推送到真实存在的远程仓库，"
            "确认未登录状态可访问，再把 URL 填入提交表。当前仓库没有 remote，也没有已推送的历史版本。"
        )
        remaining_links = "公开仓库地址与公开视频链接均未勾选"
    video_line = (
        "2. **公开视频链接**：把 `03-演示视频/reviveos-film-4min.mp4` 上传到评审可访问的平台，"
        "确认无需登录、无提取码或单独注明，再填入播放页 URL。"
    )
    repro_line = (
        "源码安装、启动、测试和生产编排见 `05-源码/ReviveOS/README.md`、`DELIVERY.md` 与 "
        "`docs/production-readiness.md`。"
        "完整复生路径需要 Docker、PostgreSQL、Redis 与 S3；仅解压源码不会自动启动服务。"
    )
    return f"""# ReviveOS 提交包

生成日期：2026-10-30  
源码版本：`{git["commit"]}`（工作区含 {git["dirty_entries"]} 项未提交改动，非 Git tag）  
公开仓库：{git["repository_url"] or "未配置"}  
公开视频：尚无播放链接

## 包内结构

| 路径 | 内容 |
| --- | --- |
| `01-作品介绍/` | 作品介绍 PDF（{pdf_pages_map["intro"]} 页）与可编辑 HTML |
| `02-使用方案/` | 详细使用方案 PDF（{pdf_pages_map["usage"]} 页）、Markdown 与 HTML |
| `03-演示视频/` | 四分钟发布片；可选 80 秒宣传片 |
| `04-提交信息/` | 提交材料清单与视频参数 |
| `05-源码/ReviveOS/` | 源码、测试、依赖锁与部署配置（{source_count} 个文件，{source_mib:.2f} MiB） |
| `SHA256SUMS.txt` | 本包内除自身外所有文件的 SHA-256 |

## 提交前仍需完成

{repository_line}
{video_line}
3. **重新核对提交表**：`04-提交信息/ReviveOS-提交材料.md` 中{remaining_links}。

## 已核验的素材

| 素材 | 核验结果 |
| --- | --- |
| 作品介绍 PDF | {pdf_pages_map["intro"]} 页，`%PDF` 文件头 |
| 使用方案 PDF | {pdf_pages_map["usage"]} 页，`%PDF` 文件头 |
| 四分钟发布片 | 1920×1080，{video_info["duration"]} 秒，H.264 + AAC，含音轨 |
| 源码 | 不含 `.git`、`.env`、密钥、依赖缓存、虚拟环境与本机运行产物 |

四分钟发布片为 `03-演示视频/reviveos-film-4min.mp4`；80 秒宣传片是可选项，不作为四分钟演示提交。

## 未打包内容

- `.git` 历史、`.env` 与任何真实密钥
- `.venv`、`node_modules`、`.next`、构建产物、数据库、胶囊与本机任务目录
- `.scratch`、逐帧预览、Edge 配置、旧版视频与原始录屏
- `docs/tasks/`、`docs/agents/`、`docs/未完成任务提示词.md` 与 `research/` 等内部协作材料
- `vibe_images/` 与 `promo/` 中的非成片素材

## 复现

{repro_line}

提交材料中的生产验收结论由项目方确认；源码文档仍保留环境限制与未覆盖项，提交前请以实际部署环境复核。
"""


def main() -> int:
    destination = DEST_DIR / f"{PACKAGE_NAME}.zip"
    partial = DEST_DIR / f"{PACKAGE_NAME}.zip.part"
    assert not destination.exists(), f"Refusing to overwrite: {destination}"
    assert not partial.exists(), f"Stale partial archive: {partial}"
    for _, path in ARTIFACTS:
        assert path.is_file(), f"Missing deliverable: {path}"

    intro_pages = pdf_pages(ROOT / "docs/ReviveOS-作品介绍.pdf")
    usage_pages = pdf_pages(ROOT / "docs/ReviveOS-使用方案.pdf")
    assert intro_pages == 7, f"Unexpected intro PDF pages: {intro_pages}"
    assert usage_pages == 17, f"Unexpected usage PDF pages: {usage_pages}"

    film = ROOT / "promo/out/reviveos-film-4min.mp4"
    film_info = mp4_info(film)
    assert 235 <= float(film_info["duration"]) <= 245, film_info
    assert film_info["has_audio"] is True, film_info

    source = source_entries()
    source_count = len(source)
    source_bytes = sum(entry.source.stat().st_size for entry in source if entry.source)
    assert source_count >= 400, source_count
    assert any(entry.archive.endswith("pyproject.toml") for entry in source)
    assert any(entry.archive.endswith("infra/compose/prod.docker-compose.yml") for entry in source)
    assert any("tests/unit/api/test_api_key_expiry.py" in entry.archive for entry in source)

    git = git_state()
    manifest = build_manifest(
        {"intro": intro_pages, "usage": usage_pages},
        film_info,
        source_count,
        source_bytes,
        git,
    )

    records: list[Record] = []
    with zipfile.ZipFile(
        partial,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as zf:
        add_bytes(zf, Entry(f"{ARCHIVE_ROOT}/00-提交包说明.md", None, manifest.encode("utf-8")), records)
        for name, path in ARTIFACTS:
            compress = path.suffix.lower() not in {".mp4", ".mov", ".m4v"}
            add_file(zf, Entry(f"{ARCHIVE_ROOT}/{name}", path, compress=compress), records)
        for entry in source:
            add_file(zf, Entry(f"{ARCHIVE_ROOT}/{entry.archive}", entry.source), records)
        checksums = "".join(
            f"{record.sha256}  {record.archive.removeprefix(ARCHIVE_ROOT + '/')}\n"
            for record in sorted(records, key=lambda item: item.archive)
        )
        add_bytes(
            zf,
            Entry(f"{ARCHIVE_ROOT}/SHA256SUMS.txt", None, checksums.encode("utf-8")),
            records,
        )

    with zipfile.ZipFile(partial) as zf:
        assert zf.testzip() is None, "ZIP CRC check failed"
        names = zf.namelist()
        assert len(names) == len(set(names)), "Duplicate archive entries"
        assert len(names) == source_count + len(ARTIFACTS) + 2
        assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
        forbidden = [
            name
            for name in names
            if "/.git/" in name
            or "/node_modules/" in name
            or name.endswith("/.env")
            or "/.venv/" in name
            or "/.scratch/" in name
            or "/__pycache__/" in name
        ]
        assert not forbidden, forbidden[:10]
        checksum_text = zf.read(f"{ARCHIVE_ROOT}/SHA256SUMS.txt").decode("utf-8")
        assert len(checksum_text.splitlines()) == len(names) - 1
        for required in (
            f"{ARCHIVE_ROOT}/01-作品介绍/ReviveOS-作品介绍.pdf",
            f"{ARCHIVE_ROOT}/02-使用方案/ReviveOS-使用方案.pdf",
            f"{ARCHIVE_ROOT}/03-演示视频/reviveos-film-4min.mp4",
            f"{ARCHIVE_ROOT}/05-源码/ReviveOS/README.md",
        ):
            assert required in names, required

    partial.replace(destination)
    summary = {
        "zip": str(destination),
        "bytes": destination.stat().st_size,
        "entries": len(names),
        "source_files": source_count,
        "source_mib": round(source_bytes / 1024 / 1024, 2),
        "intro_pages": intro_pages,
        "usage_pages": usage_pages,
        "film": film_info,
        "film_sha256": sha256_file(film),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        (DEST_DIR / f"{PACKAGE_NAME}.zip.part").unlink(missing_ok=True)
        raise
