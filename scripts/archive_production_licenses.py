"""Archive and verify production dependency license texts for the Windows release set."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import tempfile
import tomllib
from collections import deque
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ARCHIVE_FORMAT = "hengjian-production-licenses-v1"
LICENSE_PATTERN = re.compile(
    r"^(licen[cs]e|copying|notice|copyright)(\..*)?$",
    flags=re.IGNORECASE,
)


class LicenseArchiveError(RuntimeError):
    """Raised when the dependency inventory or license archive is incomplete."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _declared_python_license(distribution: importlib.metadata.Distribution) -> str:
    expression = distribution.metadata.get("License-Expression")
    if expression:
        return expression.strip()
    legacy = distribution.metadata.get("License")
    if legacy and "\n" not in legacy and len(legacy) <= 200:
        return legacy.strip()
    classifiers = distribution.metadata.get_all("Classifier") or []
    licenses = [
        classifier.removeprefix("License :: ")
        for classifier in classifiers
        if classifier.startswith("License :: ")
    ]
    return " OR ".join(licenses) if licenses else "SEE_ARCHIVED_LICENSE_TEXT"


def _python_production_distributions() -> tuple[list[dict[str, Any]], set[str]]:
    try:
        root = importlib.metadata.distribution("hengjian-audit-platform")
    except importlib.metadata.PackageNotFoundError as error:
        raise LicenseArchiveError("Run this command through `uv run` from the repository") from error

    initial_requirements = [Requirement(raw) for raw in root.requires or []]
    direct_names = {canonicalize_name(requirement.name) for requirement in initial_requirements}
    queue: deque[tuple[Requirement, set[str]]] = deque(
        (requirement, {""}) for requirement in initial_requirements
    )
    requested_extras: dict[str, set[str]] = {}
    distributions: dict[str, importlib.metadata.Distribution] = {}

    while queue:
        requirement, parent_contexts = queue.popleft()
        if requirement.marker and not any(
            requirement.marker.evaluate({"extra": context}) for context in parent_contexts
        ):
            continue
        normalized_name = canonicalize_name(requirement.name)
        extras = set(requirement.extras)
        previous_extras = requested_extras.get(normalized_name)
        if previous_extras is not None and extras <= previous_extras:
            continue
        requested_extras.setdefault(normalized_name, set()).update(extras)
        try:
            distribution = importlib.metadata.distribution(requirement.name)
        except importlib.metadata.PackageNotFoundError as error:
            raise LicenseArchiveError(
                f"Installed production dependency is missing: {requirement.name}"
            ) from error
        distributions[normalized_name] = distribution
        contexts = {"", *requested_extras[normalized_name]}
        for raw_dependency in distribution.requires or []:
            queue.append((Requirement(raw_dependency), contexts))

    result: list[dict[str, Any]] = []
    for normalized_name in sorted(distributions):
        distribution = distributions[normalized_name]
        license_files = []
        for entry in distribution.files or []:
            if LICENSE_PATTERN.match(entry.name) or "licenses" in {
                part.lower() for part in entry.parts
            }:
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    license_files.append((entry.as_posix(), source))
        if not license_files:
            raise LicenseArchiveError(
                f"No license text found in installed Python package: {normalized_name}"
            )
        result.append(
            {
                "ecosystem": "python",
                "name": distribution.metadata.get("Name") or normalized_name,
                "normalized_name": normalized_name,
                "version": distribution.version,
                "declared_license": _declared_python_license(distribution),
                "direct": normalized_name in direct_names,
                "license_sources": license_files,
            }
        )
    return result, direct_names


def _locked_python_versions(repository: Path) -> dict[str, str]:
    lock = tomllib.loads((repository / "uv.lock").read_text(encoding="utf-8"))
    return {
        canonicalize_name(package["name"]): str(package["version"])
        for package in lock["package"]
        if "version" in package and package.get("source", {}).get("editable") != "."
    }


def _frontend_production_packages(repository: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    frontend = repository / "frontend"
    lock = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
    package_json = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    direct_names = set(package_json.get("dependencies", {}))
    installed: list[dict[str, Any]] = []
    not_installed: list[dict[str, str]] = []

    for lock_path, entry in sorted(lock["packages"].items()):
        if not lock_path or entry.get("dev", False):
            continue
        package_root = frontend / Path(lock_path)
        if not package_root.is_dir():
            not_installed.append(
                {
                    "lock_path": lock_path,
                    "version": str(entry.get("version", "")),
                    "declared_license": str(entry.get("license", "")),
                }
            )
            continue
        installed_metadata = json.loads(
            (package_root / "package.json").read_text(encoding="utf-8")
        )
        name = str(installed_metadata["name"])
        version = str(installed_metadata["version"])
        if version != str(entry.get("version")):
            raise LicenseArchiveError(
                f"Frontend installed/locked version mismatch: {name} {version}"
            )
        license_files = sorted(
            path
            for path in package_root.rglob("*")
            if path.is_file() and LICENSE_PATTERN.match(path.name)
        )
        license_source_package = name
        if not license_files and name.startswith("@napi-rs/canvas-"):
            shared_root = frontend / "node_modules" / "@napi-rs" / "canvas"
            license_files = sorted(
                path
                for path in shared_root.rglob("*")
                if path.is_file() and LICENSE_PATTERN.match(path.name)
            )
            license_source_package = "@napi-rs/canvas"
        if not license_files:
            raise LicenseArchiveError(f"No license text found in frontend package: {name}")
        installed.append(
            {
                "ecosystem": "npm",
                "name": name,
                "version": version,
                "declared_license": str(
                    installed_metadata.get("license") or entry.get("license") or ""
                ),
                "direct": name in direct_names,
                "lock_path": lock_path,
                "license_source_package": license_source_package,
                "license_sources": [
                    (path.relative_to(frontend).as_posix(), path) for path in license_files
                ],
            }
        )
    return installed, not_installed


def _safe_archive_name(name: str, version: str) -> str:
    normalized = name.lower().replace("@", "").replace("/", "__")
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", normalized)
    return f"{normalized}-{version}.txt"


def _normalized_license_text(value: bytes) -> str:
    text = value.decode("utf-8-sig", errors="replace")
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _combined_license_text(package: dict[str, Any]) -> bytes:
    lines = [
        f"Package: {package['name']}",
        f"Version: {package['version']}",
        f"Declared-License: {package['declared_license']}",
    ]
    if package.get("license_source_package"):
        lines.append(f"License-Source-Package: {package['license_source_package']}")
    sections = ["\n".join(lines)]
    for source_name, source_path in package["license_sources"]:
        content = _normalized_license_text(source_path.read_bytes())
        sections.append(
            f"===== BEGIN {source_name} =====\n"
            f"{content}\n"
            f"===== END {source_name} ====="
        )
    return ("\n\n".join(sections) + "\n").encode("utf-8")


def generate_archive(repository: Path, output_dir: Path) -> dict[str, Any]:
    repository = repository.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise LicenseArchiveError(f"Archive directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    python_packages, _ = _python_production_distributions()
    locked_versions = _locked_python_versions(repository)
    frontend_packages, frontend_not_installed = _frontend_production_packages(repository)
    manifest_packages: list[dict[str, Any]] = []

    for package in [*python_packages, *frontend_packages]:
        if package["ecosystem"] == "python":
            locked_version = locked_versions.get(package["normalized_name"])
            if locked_version != package["version"]:
                raise LicenseArchiveError(
                    "Python installed/locked version mismatch: "
                    f"{package['name']} installed={package['version']} locked={locked_version}"
                )
        ecosystem_directory = output_dir / package["ecosystem"]
        ecosystem_directory.mkdir(exist_ok=True)
        archive_name = _safe_archive_name(package["name"], package["version"])
        archive_path = ecosystem_directory / archive_name
        content = _combined_license_text(package)
        archive_path.write_bytes(content)
        manifest_entry = {
            key: value
            for key, value in package.items()
            if key not in {"license_sources", "normalized_name"}
        }
        manifest_entry.update(
            {
                "archive_path": archive_path.relative_to(output_dir).as_posix(),
                "archive_sha256": _sha256_bytes(content),
                "source_files": [name for name, _ in package["license_sources"]],
            }
        )
        manifest_packages.append(manifest_entry)

    manifest = {
        "format": ARCHIVE_FORMAT,
        "target": "Windows x86_64 production environment",
        "inputs": {
            "uv.lock": _sha256_file(repository / "uv.lock"),
            "frontend/package-lock.json": _sha256_file(
                repository / "frontend" / "package-lock.json"
            ),
        },
        "python_package_count": len(python_packages),
        "frontend_installed_package_count": len(frontend_packages),
        "frontend_locked_optional_not_installed": frontend_not_installed,
        "packages": sorted(
            manifest_packages,
            key=lambda item: (str(item["ecosystem"]), str(item["name"]).lower()),
        ),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def verify_archive(repository: Path, archive_dir: Path) -> dict[str, Any]:
    archive_dir = archive_dir.resolve()
    if not archive_dir.is_dir():
        raise LicenseArchiveError(f"Archive directory not found: {archive_dir}")
    with tempfile.TemporaryDirectory(prefix="hengjian-license-verify-") as temporary:
        generated_dir = Path(temporary) / "production"
        expected_manifest = generate_archive(repository, generated_dir)
        expected_files = {
            path.relative_to(generated_dir).as_posix(): path.read_bytes()
            for path in generated_dir.rglob("*")
            if path.is_file()
        }
        actual_files = {
            path.relative_to(archive_dir).as_posix(): path.read_bytes()
            for path in archive_dir.rglob("*")
            if path.is_file()
        }
        if expected_files.keys() != actual_files.keys():
            raise LicenseArchiveError("Archived license file set does not match production dependencies")
        changed = [
            name for name in expected_files if expected_files[name] != actual_files[name]
        ]
        if changed:
            raise LicenseArchiveError(f"Archived license files changed: {changed}")
    return {
        "format": ARCHIVE_FORMAT,
        "verified": True,
        "python_packages": expected_manifest["python_package_count"],
        "frontend_packages": expected_manifest["frontend_installed_package_count"],
        "files": len(expected_files),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    archive = commands.add_parser("archive")
    archive.add_argument("--output-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--archive-dir", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _build_parser().parse_args()
    repository = Path(__file__).resolve().parents[1]
    try:
        if arguments.command == "archive":
            manifest = generate_archive(repository, arguments.output_dir)
            result = {
                "format": ARCHIVE_FORMAT,
                "output_dir": str(arguments.output_dir.resolve()),
                "python_packages": manifest["python_package_count"],
                "frontend_packages": manifest["frontend_installed_package_count"],
            }
        else:
            result = verify_archive(repository, arguments.archive_dir)
    except LicenseArchiveError as error:
        print(f"error: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
