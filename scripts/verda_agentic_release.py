"""Freeze current allowlisted worktree bytes without committing or copying private state."""
import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PATHS = ("app", "requirements.in", "requirements.txt", "deploy/verda-agentic")
VALIDATION_PATHS = ("tests", "scripts", "docs", "README.md", "AGENTS.md", "pyproject.toml", "pytest.ini", "setup.cfg", "conftest.py")
SOURCE_PATHS = PRODUCTION_PATHS + VALIDATION_PATHS
EXCLUDED_COMPONENTS = frozenset({
    ".git", ".runtime", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    "node_modules", "uploads", "test-results", "junction-dataset", "junction-dataset-preview",
})
EXCLUDED_FILES = frozenset({"questions.jsonl", "api_keys.json", "api_key.json", "apikeys.txt", ".gemini_api_key"})


def _safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(part in {"", ".", ".."} for part in path.parts) or "\\" in name or any(ord(char) < 32 for char in name):
        raise ValueError("Unsafe snapshot member path.")
    return path


def _excluded(relative):
    return any(part in EXCLUDED_COMPONENTS or part.casefold().startswith(".env") for part in relative.parts) or relative.name in EXCLUDED_FILES


def _read_file(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Snapshot members must be ordinary files.")
        return stream.read()


def _inventory(root):
    records = {}
    for allowed in SOURCE_PATHS:
        start = root / allowed
        if start.is_symlink() or not start.exists():
            continue
        members = [start] if start.is_file() else start.rglob("*")
        for path in members:
            relative = path.relative_to(root)
            if _excluded(relative) or path.is_symlink():
                continue
            if any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
                continue
            if not path.is_file():
                continue
            name = relative.as_posix()
            _safe_name(name)
            data = _read_file(path)
            records[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                             "mode": 0o755 if path.stat().st_mode & 0o111 else 0o644}
    return dict(sorted(records.items()))


def _git_metadata(root):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    return {"branch": git("branch", "--show-current") or "DETACHED", "base_commit": git("rev-parse", "--verify", "HEAD^{commit}")}


def _content_id(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _production_member(name):
    return any(name == prefix or name.startswith(prefix + "/") for prefix in PRODUCTION_PATHS)


def prepare(source_root, output, expected_content_id=None):
    if Path(output).is_symlink():
        raise ValueError("The release output must not be a symbolic link.")
    source_root, output = Path(source_root).resolve(), Path(output).resolve()
    if not source_root.is_dir():
        raise ValueError("The source root is unavailable.")
    if output.exists():
        raise FileExistsError("Choose a new release directory; existing output is never replaced.")
    if any(output.is_relative_to(source_root / path) for path in SOURCE_PATHS):
        raise ValueError("The output must be outside the snapshotted source paths.")
    records, metadata = _inventory(source_root), _git_metadata(source_root)
    if not all(name in records for name in ("app/main.py", "requirements.in", "requirements.txt")):
        raise ValueError("The production application and both requirement files are required.")
    content_id = _content_id(records)
    if expected_content_id is not None and content_id != expected_content_id:
        raise ValueError("The current source differs from the expected content ID; nothing was frozen.")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + output.name + "-", dir=output.parent))
    try:
        frozen = stage / "source"
        frozen.mkdir()
        for name, record in records.items():
            data = _read_file(source_root / name)
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("Source changed while freezing; no release was published.")
            destination = frozen / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            destination.chmod(0o555 if record["mode"] == 0o755 else 0o444)
        if _inventory(source_root) != records or _git_metadata(source_root) != metadata:
            raise ValueError("Source changed while freezing; no release was published.")
        archive = stage / "application.tar"
        production = {name: record for name, record in records.items() if _production_member(name)}
        with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as bundle:
            for name, record in production.items():
                data = (frozen / name).read_bytes()
                member = tarfile.TarInfo(name)
                member.size, member.mode, member.mtime = len(data), record["mode"], 0
                member.uid = member.gid = 0
                member.uname = member.gname = ""
                bundle.addfile(member, BytesIO(data))
        result = {"version": 1, **metadata, "source_kind": "worktree_snapshot", "content_id": content_id,
                  "created_at": datetime.now(timezone.utc).isoformat(), "archive": archive.name,
                  "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                  "production_paths": list(PRODUCTION_PATHS), "validation_paths": list(VALIDATION_PATHS),
                  "files": records, "production_files": list(production)}
        (stage / "release.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        verify(stage)
        stage.rename(output)
        return result
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify(output):
    """Verify validation source and every archive member against the frozen manifest."""
    output = Path(output)
    result = json.loads((output / "release.json").read_text())
    records = result["files"]
    if _inventory(output / "source") != records or _content_id(records) != result["content_id"]:
        raise ValueError("Frozen validation source failed its content manifest.")
    if result["production_files"] != [name for name in records if _production_member(name)]:
        raise ValueError("Production files differ from the deployment allowlist.")
    archive = output / result["archive"]
    if result["archive"] != "application.tar" or hashlib.sha256(archive.read_bytes()).hexdigest() != result["sha256"]:
        raise ValueError("Application archive failed its hash manifest.")
    with tarfile.open(archive, "r") as bundle:
        seen = set()
        for member in bundle:
            _safe_name(member.name)
            if member.name in seen or member.name not in result["production_files"] or not member.isfile():
                raise ValueError("Unexpected or unsafe production archive member.")
            seen.add(member.name)
            record = records[member.name]
            if member.mode != record["mode"] or hashlib.sha256(bundle.extractfile(member).read()).hexdigest() != record["sha256"]:
                raise ValueError("Archive bytes differ from the frozen validation source.")
        if seen != set(result["production_files"]):
            raise ValueError("The production archive is incomplete.")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-content-id")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if bool(args.output) == bool(args.verify):
        parser.error("Choose either --output or --verify.")
    result = verify(args.verify) if args.verify else prepare(args.source_root, args.output, args.expected_content_id)
    print(json.dumps({key: result[key] for key in ("branch", "base_commit", "content_id", "sha256")}))
