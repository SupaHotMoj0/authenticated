"""Tests for HACS repository structure compliance."""

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "custom_components", "authenticated")


def test_custom_components_dir_exists():
    """Integration files must be under custom_components/<domain>/."""
    assert os.path.isdir(os.path.join(REPO_ROOT, "custom_components"))
    assert os.path.isdir(SRC_DIR)


def test_only_one_integration_in_custom_components():
    """HACS requires exactly one subdirectory under custom_components/."""
    cc_dir = os.path.join(REPO_ROOT, "custom_components")
    subdirs = [
        d for d in os.listdir(cc_dir)
        if os.path.isdir(os.path.join(cc_dir, d)) and not d.startswith(".")
    ]
    assert len(subdirs) == 1, f"Expected 1 integration, found: {subdirs}"
    assert subdirs[0] == "authenticated"


def test_required_integration_files_exist():
    """All required integration files must be inside custom_components/authenticated/."""
    required = ["__init__.py", "manifest.json", "const.py", "sensor.py", "providers.py"]
    for fname in required:
        path = os.path.join(SRC_DIR, fname)
        assert os.path.isfile(path), f"Missing required file: {fname}"


def test_no_integration_files_at_repo_root():
    """Integration files must NOT be at the repo root (HACS 'Not OK example 2')."""
    root_files = ["__init__.py", "manifest.json", "sensor.py", "providers.py", "const.py"]
    for fname in root_files:
        path = os.path.join(REPO_ROOT, fname)
        assert not os.path.isfile(path), (
            f"{fname} found at repo root — must be under custom_components/authenticated/"
        )


def test_manifest_has_hacs_required_keys():
    """manifest.json must have all keys required by HACS."""
    with open(os.path.join(SRC_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    required_keys = ["domain", "documentation", "issue_tracker", "codeowners", "name", "version"]
    for key in required_keys:
        assert key in manifest, f"manifest.json missing HACS-required key: {key}"


def test_hacs_json_exists():
    """hacs.json should exist at the repo root."""
    assert os.path.isfile(os.path.join(REPO_ROOT, "hacs.json"))


def test_hacs_json_valid():
    """hacs.json must be valid JSON with a name field."""
    with open(os.path.join(REPO_ROOT, "hacs.json")) as f:
        data = json.load(f)
    assert "name" in data
