"""Frozen worktree packaging uses exact bytes and never includes private runtime state."""
import importlib.util
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pack(monkeypatch):
    spec = importlib.util.spec_from_file_location("verda_agentic_release", ROOT / "scripts/verda_agentic_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_git_metadata", lambda root: {"branch": "fixture-agentic", "base_commit": "a" * 40})
    return module


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "worktree"
    for name, data in {
        "app/main.py": b"# fixture main\n", "app/untracked_agent.py": b"# untracked current code\n",
        "app/static/concrete-logo.png": b"fixture-logo-bytes", "requirements.in": b"fixture-package\n",
        "requirements.txt": b"fixture-package==1\n", "tests/test_fixture.py": b"def test_example(): pass\n",
        "scripts/test.sh": b"#!/bin/sh\nexit 0\n", "docs/CONTRACT.md": b"Fixture contract\n",
        "deploy/verda-agentic/blueprint-agentic.service": b"Fixture isolated service\n",
        "deploy/verda-agentic/Caddyfile": b"Fixture new hostname\n", "README.md": b"Fixture readme\n",
        "app/.env.local": b"private-fixture-value", ".env.local": b"private-root-fixture-value",
        "app/__pycache__/main.pyc": b"cache", "tests/.pytest_cache/result": b"cache",
        ".runtime/buildings/private/source.original": b"private-upload", "assets/junction-dataset/questions.jsonl": b"private-answer",
        "app/questions.jsonl": b"private-answer", "deploy/verda/Caddyfile": b"old-host-config",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "scripts/test.sh").chmod(0o755)
    (root / "app/linked-env").symlink_to(root / ".env.local")
    (root / "app/linked-directory").symlink_to(root / ".runtime", target_is_directory=True)
    return root


def test_untracked_code_and_logo_are_frozen_but_private_state_is_excluded(pack, source, tmp_path):
    output = tmp_path / "release"
    result = pack.prepare(source, output)
    assert result["branch"] == "fixture-agentic" and result["base_commit"] == "a" * 40
    assert {"app/untracked_agent.py", "app/static/concrete-logo.png"} <= result["files"].keys()
    assert not any(".env" in name or "__pycache__" in name or "questions.jsonl" in name or "linked" in name for name in result["files"])
    with tarfile.open(output / "application.tar") as archive:
        names = archive.getnames()
        assert "app/untracked_agent.py" in names and "app/static/concrete-logo.png" in names
        assert not any(name.startswith(("tests/", "scripts/", "docs/", "assets/", ".runtime/", "deploy/verda/")) for name in names)
        for member in archive:
            assert archive.extractfile(member).read() == (output / "source" / member.name).read_bytes()
            assert member.mtime == 0 and not member.issym()
    assert (output / "source/tests/test_fixture.py").exists()
    assert pack.verify(output) == result


def test_identical_bytes_produce_identical_content_and_archive_hashes(pack, source, tmp_path):
    first = pack.prepare(source, tmp_path / "first")
    (source / "app/main.py").touch()
    second = pack.prepare(source, tmp_path / "second", expected_content_id=first["content_id"])
    assert first["content_id"] == second["content_id"] and first["sha256"] == second["sha256"]
    with pytest.raises(FileExistsError):
        pack.prepare(source, tmp_path / "first")


def test_source_mutation_during_freeze_publishes_nothing(pack, source, tmp_path, monkeypatch):
    read = pack._read_file
    calls = 0
    def mutate(path):
        nonlocal calls
        if path == source / "app/main.py":
            calls += 1
            if calls == 2:
                path.write_bytes(b"changed while copying")
        return read(path)
    monkeypatch.setattr(pack, "_read_file", mutate)
    with pytest.raises(ValueError, match="Source changed"):
        pack.prepare(source, tmp_path / "release")
    assert not (tmp_path / "release").exists()
    assert not list(tmp_path.glob(".release-*"))


def test_wrong_expected_id_and_unsafe_output_paths_fail_before_publication(pack, source, tmp_path):
    with pytest.raises(ValueError, match="expected content ID"):
        pack.prepare(source, tmp_path / "release", expected_content_id="0" * 64)
    with pytest.raises(ValueError, match="outside"):
        pack.prepare(source, source / "app/nested-release")
    for name in ("../escape", "/absolute", "app/../escape", "app\\escape", "app/bad\nname", "app//double", "app/./dot"):
        with pytest.raises(ValueError, match="Unsafe"):
            pack._safe_name(name)
    (tmp_path / "linked-output").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symbolic link"):
        pack.prepare(source, tmp_path / "linked-output")
    assert not (tmp_path / "outside").exists()


def test_frozen_source_tampering_is_detected(pack, source, tmp_path):
    output = tmp_path / "release"
    pack.prepare(source, output)
    path = output / "source/app/main.py"
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="validation source"):
        pack.verify(output)


def test_isolated_templates_never_replace_old_service_or_public_app_port():
    service = (ROOT / "deploy/verda-agentic/blueprint-agentic.service").read_text()
    site = (ROOT / "deploy/verda-agentic/Caddyfile").read_text()
    assert "RequiresMountsFor=/srv/blueprint-data" in service
    assert "ConditionPathIsMountPoint=/srv/blueprint-data" in service
    assert "ReadWritePaths=/srv/blueprint-data/agentic/runtime\n" in service
    assert "User=blueprint-agentic" in service and "WorkingDirectory=/opt/blueprint-agentic/current" in service
    assert "EnvironmentFile=/etc/blueprint-agentic/application.env" in service
    assert "--host 127.0.0.1 --port 8001 --workers 1" in service and "--no-access-log" in service
    assert "TimeoutStopSec=infinity" in service
    assert "agentic.95.133.254.90.sslip.io {" in site and "reverse_proxy 127.0.0.1:8001" in site
    assert "blueprint-qa.service" not in service and "127.0.0.1:8000" not in site
