#!/usr/bin/env python3
"""Discover launcher instances and safely inspect/install Minecraft content.

The command line interface deliberately uses only the Python standard library so
it can run inside HMCL/Codex environments without a package installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import sys
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


MAX_ARCHIVE_COMPRESSED = 512 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED = 8 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 100_000
MAX_MEMBER_UNCOMPRESSED = 512 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
SKIP_NAMES = {".DS_Store"}
SKIP_PREFIXES = ("._",)
WORLD_DIRS = {
    "advancements",
    "data",
    "datapacks",
    "entities",
    "playerdata",
    "poi",
    "region",
    "structures",
}
VERSION_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)")


class ContentError(RuntimeError):
    """An expected user-facing content or safety error."""


def safe_parts(name: str) -> tuple[str, ...] | None:
    """Normalize a ZIP member and reject traversal or absolute paths."""

    if not name or "\x00" in name:
        return None
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or re.match(r"^[A-Za-z]:/", normalized):
        return None
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if any(part == ".." for part in parts):
        return None
    return parts


def should_skip(parts: tuple[str, ...]) -> bool:
    if not parts:
        return True
    return parts[0] == "__MACOSX" or any(
        part in SKIP_NAMES or part.startswith(SKIP_PREFIXES) for part in parts
    )


def clean_name(value: str) -> str:
    value = re.sub(r"\u00a7.", "", value)
    value = value.replace("\\", " ")
    value = re.sub(r"[/:*?\"<>|]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or "Minecraft World"


def json_from_bytes(raw: bytes, label: str) -> dict[str, Any] | None:
    if len(raw) > MAX_METADATA_BYTES:
        raise ContentError(f"Metadata file is too large: {label}")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_zip_member(zf: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_METADATA_BYTES:
        raise ContentError(f"Metadata file is too large: {name}")
    with zf.open(info) as stream:
        return stream.read(MAX_METADATA_BYTES + 1)


def archive_members(path: Path) -> tuple[list[zipfile.ZipInfo], dict[str, str]]:
    if not path.is_file():
        raise ContentError(f"File does not exist: {path}")
    if path.stat().st_size > MAX_ARCHIVE_COMPRESSED:
        raise ContentError("Archive is larger than the 512 MiB safety limit")
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ContentError(f"Not a readable ZIP/JAR archive: {path}") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVE_FILES:
            raise ContentError("Archive contains too many files")
        total = 0
        seen: dict[str, str] = {}
        for info in infos:
            parts = safe_parts(info.filename)
            if parts is None:
                raise ContentError(f"Unsafe archive path: {info.filename!r}")
            if info.flag_bits & 0x1:
                raise ContentError(f"Encrypted archive member is not accepted: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ContentError(f"Symlink archive member is not accepted: {info.filename}")
            normalized = "/".join(parts).casefold()
            if normalized and normalized in seen:
                raise ContentError(
                    f"Duplicate archive path after normalization: {info.filename!r}"
                )
            if normalized:
                seen[normalized] = info.filename
            if info.file_size > MAX_MEMBER_UNCOMPRESSED:
                raise ContentError(f"Archive member is too large: {info.filename}")
            total += info.file_size
            if total > MAX_ARCHIVE_UNCOMPRESSED:
                raise ContentError("Archive expands beyond the 8 GiB safety limit")
        return infos, seen


def archive_names(infos: Iterable[zipfile.ZipInfo]) -> set[str]:
    names: set[str] = set()
    for info in infos:
        parts = safe_parts(info.filename)
        if parts and not should_skip(parts):
            names.add("/".join(parts))
    return names


def find_world_roots(infos: Iterable[zipfile.ZipInfo]) -> list[tuple[str, ...]]:
    roots: list[tuple[str, ...]] = []
    for info in infos:
        parts = safe_parts(info.filename)
        if parts and parts[-1].casefold() == "level.dat" and not should_skip(parts):
            roots.append(parts[:-1])
    return roots


def world_score(infos: Iterable[zipfile.ZipInfo], root: tuple[str, ...]) -> tuple[int, int, int]:
    directories: set[str] = set()
    region_files = 0
    files = 0
    for info in infos:
        parts = safe_parts(info.filename)
        if not parts or parts[: len(root)] != root:
            continue
        relative = parts[len(root) :]
        if not relative or should_skip(relative):
            continue
        if relative[0] in WORLD_DIRS:
            directories.add(relative[0])
        if not info.is_dir():
            files += 1
            if relative[0] == "region":
                region_files += 1
    return len(directories), region_files, files


def find_world_root(infos: list[zipfile.ZipInfo]) -> tuple[str, ...]:
    roots = find_world_roots(infos)
    if not roots:
        raise ContentError("No level.dat found; this is not a Minecraft world archive")
    return max(roots, key=lambda root: (world_score(infos, root), -len(root), root))


def unique_destination(parent: Path, requested: str) -> Path:
    parent = parent.resolve()
    base = clean_name(requested)
    candidate = parent / base
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        candidate = parent / f"{base} {index}"
        if not candidate.exists():
            return candidate
    raise ContentError(f"Could not find an unused destination for {base!r}")


def extract_world(archive: Path, saves_dir: Path, name: str | None = None) -> tuple[Path, int]:
    infos, _ = archive_members(archive)
    root = find_world_root(infos)
    saves_dir = saves_dir.expanduser().resolve()
    saves_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(saves_dir, name or (root[-1] if root else archive.stem))
    temp = saves_dir / f".install-{os.getpid()}-{time.time_ns()}"
    temp.mkdir()
    written = 0
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in infos:
                parts = safe_parts(info.filename)
                if parts is None or parts[: len(root)] != root:
                    continue
                relative = parts[len(root) :]
                if should_skip(relative):
                    continue
                target = temp.joinpath(*relative)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                written += 1
        if not (temp / "level.dat").is_file():
            raise ContentError("Extraction finished but level.dat is missing")
        os.replace(temp, destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return destination, written


def copy_world(source: Path, target_game_dir: Path, name: str | None, replace: bool) -> tuple[Path, int]:
    source = source.expanduser().resolve()
    if not source.is_dir() or not (source / "level.dat").is_file():
        raise ContentError(f"Source is not a Minecraft world directory: {source}")
    saves_dir = resolve_game_dir(target_game_dir) / "saves"
    saves_dir.mkdir(parents=True, exist_ok=True)
    destination = saves_dir / clean_name(name or source.name)
    if destination.exists() and not replace:
        raise ContentError(f"Destination exists; use --replace to update it: {destination}")
    temp = saves_dir / f".sync-{os.getpid()}-{time.time_ns()}"
    temp.mkdir()
    count = 0
    try:
        for root, dirs, files in os.walk(source, followlinks=False):
            root_path = Path(root)
            symlink_dirs = [d for d in dirs if (root_path / d).is_symlink()]
            if symlink_dirs:
                raise ContentError(f"World contains symlink directories: {symlink_dirs}")
            dirs[:] = sorted(dirs)
            for filename in sorted(files):
                source_file = root_path / filename
                if source_file.is_symlink():
                    raise ContentError(f"World contains a symlink: {source_file}")
                relative = source_file.relative_to(source)
                target = temp / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target)
                count += 1
        if not (temp / "level.dat").is_file():
            raise ContentError("Sync finished but level.dat is missing")
        if destination.exists():
            backup = saves_dir / f".{destination.name}.backup-{time.strftime('%Y%m%d-%H%M%S')}"
            os.replace(destination, backup)
            try:
                os.replace(temp, destination)
            except Exception:
                if not destination.exists() and backup.exists():
                    os.replace(backup, destination)
                raise
        else:
            os.replace(temp, destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return destination, count


def parse_properties(raw: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def parse_mod_toml(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", "replace")
    values: dict[str, Any] = {}
    for key in ("modId", "displayName", "version", "loaderVersion", "minecraftVersionRange"):
        match = re.search(rf"^\s*{key}\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
        if match:
            values[key] = match.group(1)
    mc = re.search(r"minecraft(?:VersionRange)?\s*=\s*[\"']([^\"']+)[\"']", text)
    if mc:
        values["minecraft"] = mc.group(1)
    return values


def inspect_archive(path: Path) -> dict[str, Any]:
    infos, _ = archive_members(path)
    names = archive_names(infos)
    result: dict[str, Any] = {
        "path": str(path.expanduser().resolve()),
        "kind": "unknown",
        "signals": [],
        "minecraft_versions": [],
        "loaders": [],
    }
    if find_world_roots(infos):
        result["kind"] = "world"
        result["signals"].append("level.dat")
    metadata: dict[str, Any] = {}
    with zipfile.ZipFile(path) as zf:
        for filename in ("fabric.mod.json", "quilt.mod.json"):
            raw = read_zip_member(zf, filename)
            if raw is not None:
                parsed = json_from_bytes(raw, filename)
                if parsed:
                    metadata[filename] = parsed
        for filename in ("META-INF/mods.toml", "META-INF/neoforge.mods.toml"):
            raw = read_zip_member(zf, filename)
            if raw is not None:
                metadata[filename] = parse_mod_toml(raw)
        for filename in ("manifest.json", "modrinth.index.json", "mmc-pack.json", "instance.cfg"):
            raw = read_zip_member(zf, filename)
            if raw is not None:
                metadata[filename] = (
                    parse_properties(raw)
                    if filename == "instance.cfg"
                    else json_from_bytes(raw, filename)
                )
    if metadata.get("fabric.mod.json") or metadata.get("quilt.mod.json") or any(
        key in metadata for key in ("META-INF/mods.toml", "META-INF/neoforge.mods.toml")
    ):
        result["kind"] = "mod"
        result["signals"].extend(key for key in metadata if key.endswith(".json") or key.endswith(".toml"))
        result["metadata"] = metadata
        result["compatibility"] = mod_compatibility(metadata)
    pack = pack_compatibility(metadata)
    if pack:
        result["kind"] = "modpack"
        result["signals"].extend(pack.pop("signals", []))
        result["pack"] = pack
    if "pack.mcmeta" in names and result["kind"] == "unknown":
        result["kind"] = "resource-pack"
    if any(name == "shaders" or name.startswith("shaders/") for name in names):
        result["kind"] = "shaderpack"
        result["signals"].append("shaders/")
    result["signals"] = sorted(set(result["signals"]))
    if result.get("compatibility"):
        result["minecraft_versions"] = result["compatibility"].get("minecraft", [])
        result["loaders"] = result["compatibility"].get("loaders", [])
    elif result.get("pack"):
        result["minecraft_versions"] = result["pack"].get("minecraft", [])
        result["loaders"] = result["pack"].get("loaders", [])
    return result


def mod_compatibility(metadata: dict[str, Any]) -> dict[str, Any]:
    minecraft: list[str] = []
    loaders: list[str] = []
    for filename, data in metadata.items():
        if filename == "fabric.mod.json" and isinstance(data, dict):
            depends = data.get("depends", {})
            if isinstance(depends, dict) and depends.get("minecraft") is not None:
                minecraft.append(str(depends["minecraft"]))
            if isinstance(depends, dict) and depends.get("fabricloader") is not None:
                loaders.append(f"fabric-loader {depends['fabricloader']}")
        elif filename == "quilt.mod.json" and isinstance(data, dict):
            depends = data.get("quilt_loader", {}).get("depends", [])
            for dependency in depends if isinstance(depends, list) else []:
                if isinstance(dependency, dict) and dependency.get("id") == "minecraft":
                    minecraft.append(str(dependency.get("versions", "*")))
                if isinstance(dependency, dict) and dependency.get("id") == "quilt_loader":
                    loaders.append(f"quilt-loader {dependency.get('versions', '*')}")
        elif filename.endswith("mods.toml") and isinstance(data, dict):
            if data.get("minecraft"):
                minecraft.append(str(data["minecraft"]))
            if data.get("loaderVersion"):
                loaders.append(str(data["loaderVersion"]))
    return {"minecraft": sorted(set(minecraft)), "loaders": sorted(set(loaders))}


def pack_compatibility(metadata: dict[str, Any]) -> dict[str, Any] | None:
    minecraft: list[str] = []
    loaders: list[str] = []
    signals: list[str] = []
    manifest = metadata.get("manifest.json")
    if isinstance(manifest, dict) and manifest.get("manifestType") == "minecraftModpack":
        signals.append("manifest.json")
        mc = manifest.get("minecraft", {})
        if isinstance(mc, dict) and mc.get("version"):
            minecraft.append(str(mc["version"]))
            for loader in mc.get("modLoaders", []):
                if isinstance(loader, dict) and loader.get("id"):
                    loaders.append(str(loader["id"]))
    index = metadata.get("modrinth.index.json")
    if isinstance(index, dict) and index.get("formatVersion") is not None:
        signals.append("modrinth.index.json")
        deps = index.get("dependencies", {})
        if isinstance(deps, dict):
            if deps.get("minecraft"):
                minecraft.append(str(deps["minecraft"]))
            for key in ("fabric-loader", "quilt-loader", "forge", "neoforge"):
                if deps.get(key):
                    loaders.append(f"{key} {deps[key]}")
    mmc = metadata.get("mmc-pack.json")
    if isinstance(mmc, dict):
        signals.append("mmc-pack.json")
        for component in mmc.get("components", []):
            if not isinstance(component, dict):
                continue
            uid = str(component.get("uid", ""))
            version = component.get("version")
            if uid == "net.minecraft" and version:
                minecraft.append(str(version))
            elif version and any(token in uid for token in ("fabric", "quilt", "forge", "neoforge")):
                loaders.append(f"{uid} {version}")
    return {"minecraft": sorted(set(minecraft)), "loaders": sorted(set(loaders)), "signals": signals} if signals else None


def parse_constraint(constraint: str) -> list[tuple[str, tuple[int, ...]]]:
    result: list[tuple[str, tuple[int, ...]]] = []
    for token in re.findall(r"(>=|<=|>|<|=|\^|~)?\s*(\d+(?:\.\d+){0,3}|\*)", constraint):
        op, raw = token
        if raw == "*":
            continue
        result.append((op or "=", tuple(int(part) for part in raw.split("."))))
    return result


def version_tuple(value: str) -> tuple[int, ...] | None:
    match = VERSION_RE.search(value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right))
    a = left + (0,) * (width - len(left))
    b = right + (0,) * (width - len(right))
    return (a > b) - (a < b)


def matches_constraint(version: str, constraint: str) -> bool | None:
    actual = version_tuple(version)
    if actual is None or not constraint or constraint.strip() in {"*", "any"}:
        return True if actual is not None else None
    alternatives = [item.strip() for item in constraint.split("||")]
    known = False
    for alternative in alternatives:
        wildcard = re.fullmatch(r"(\d+(?:\.\d+)?)\.x", alternative, re.IGNORECASE)
        if wildcard:
            expected = tuple(int(part) for part in wildcard.group(1).split("."))
            return actual[: len(expected)] == expected
        checks = parse_constraint(alternative)
        if not checks:
            continue
        known = True
        okay = True
        for op, expected in checks:
            comparison = compare_versions(actual, expected)
            if op == "=" and comparison != 0:
                okay = False
            elif op == ">" and comparison <= 0:
                okay = False
            elif op == ">=" and comparison < 0:
                okay = False
            elif op == "<" and comparison >= 0:
                okay = False
            elif op == "<=" and comparison > 0:
                okay = False
            elif op == "^" and (actual[0] != expected[0] or comparison < 0):
                okay = False
            elif op == "~" and (actual[:2] != expected[:2] or comparison < 0):
                okay = False
        if okay:
            return True
    return False if known else None


def compatibility_report(content: dict[str, Any], minecraft: str | None, loader: str | None) -> dict[str, Any]:
    constraints = content.get("minecraft_versions", [])
    version_checks = [matches_constraint(minecraft, item) for item in constraints] if minecraft else []
    version_ok: bool | None = None
    if version_checks:
        version_ok = any(value is True for value in version_checks) if any(value is not None for value in version_checks) else None
    loader_text = " ".join(content.get("loaders", [])).casefold()
    loader_ok = None if not loader else (not loader_text or loader.casefold() in loader_text)
    return {
        "minecraft_version": minecraft,
        "loader": loader,
        "minecraft_ok": version_ok,
        "loader_ok": loader_ok,
        "compatible": version_ok is not False and loader_ok is not False,
        "constraints": constraints,
        "loaders": content.get("loaders", []),
    }


@dataclass
class Instance:
    launcher: str
    name: str
    game_dir: str
    root: str
    minecraft_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def candidate_roots() -> list[Path]:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        app = home / "Library/Application Support"
        return [
            home / "Desktop/.minecraft",
            app / "minecraft",
            app / "PrismLauncher",
            app / "org.prismlauncher.PrismLauncher",
            app / "ModrinthApp",
            app / "com.modrinth.theseus",
            app / "curseforge/minecraft",
            app / "ATLauncher",
            app / "multimc",
        ]
    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        return [home / "AppData/Roaming/.minecraft", appdata / "PrismLauncher", local / "ModrinthApp", appdata / "ATLauncher"]
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    return [home / ".minecraft", data / "PrismLauncher", data / "ModrinthApp", data / "ATLauncher"]


def has_instance_markers(path: Path) -> bool:
    return any(
        (path / marker).is_file()
        for marker in ("instance.cfg", "mmc-pack.json", "minecraftinstance.json", "manifest.json", "modrinth.index.json", "instance.json")
    ) or (path / "versions").is_dir()


def launcher_name(path: Path) -> str:
    if (path / "instance.cfg").is_file() or (path / "mmc-pack.json").is_file():
        return "Prism/MultiMC"
    if (path / "minecraftinstance.json").is_file() or (path / "manifest.json").is_file():
        return "CurseForge"
    if (path / "modrinth.index.json").is_file() or "modrinth" in str(path).casefold():
        return "Modrinth"
    if (path / "instance.json").is_file() or "atlauncher" in str(path).casefold():
        return "ATLauncher"
    return "HMCL/Official"


def instance_game_dir(path: Path) -> Path:
    nested = path / ".minecraft"
    if nested.is_dir() and not (path / "versions").is_dir():
        return nested
    return path


def read_instance_metadata(path: Path) -> tuple[list[str], list[str], list[str]]:
    versions: list[str] = []
    loaders: list[str] = []
    evidence: list[str] = []
    cfg = path / "instance.cfg"
    if cfg.is_file():
        values = parse_properties(cfg.read_bytes())
        for key in ("IntendedVersion", "MinecraftVersion", "Version"):
            if values.get(key):
                versions.append(values[key])
        evidence.append(str(cfg))
    for filename in ("manifest.json", "modrinth.index.json", "mmc-pack.json"):
        file = path / filename
        if not file.is_file():
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        pack = pack_compatibility({filename: data})
        if pack:
            versions.extend(pack["minecraft"])
            loaders.extend(pack["loaders"])
        evidence.append(str(file))
    versions_dir = instance_game_dir(path) / "versions"
    if versions_dir.is_dir():
        for version_dir in sorted(versions_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            descriptor = version_dir / f"{version_dir.name}.json"
            if descriptor.is_file():
                versions.append(version_dir.name)
                evidence.append(str(descriptor))
    return sorted(set(versions)), sorted(set(loaders)), evidence


def discover_instances(roots: Iterable[Path] | None = None) -> list[Instance]:
    roots = [root.expanduser() for root in (roots or candidate_roots())]
    found: dict[str, Instance] = {}
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        candidates = [root]
        for container_name in ("instances", "profiles", "Instances"):
            container = root / container_name
            if container.is_dir():
                candidates.extend(item for item in container.iterdir() if item.is_dir())
        candidates.extend(item for item in root.iterdir() if item.is_dir() and not item.name.startswith("."))
        for candidate in candidates:
            if not has_instance_markers(candidate):
                continue
            game_dir = instance_game_dir(candidate).resolve()
            key = str(game_dir)
            versions, loaders, evidence = read_instance_metadata(candidate)
            found[key] = Instance(
                launcher=launcher_name(candidate),
                name=candidate.name,
                game_dir=str(game_dir),
                root=str(candidate.resolve()),
                minecraft_versions=versions,
                loaders=loaders,
                evidence=evidence,
            )
    return sorted(found.values(), key=lambda item: (item.launcher, item.name.casefold(), item.game_dir))


def resolve_game_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    nested = path / ".minecraft"
    if nested.is_dir() and not (path / "versions").is_dir():
        return nested
    return path


def install_mod(archive: Path, target: Path, minecraft: str | None, loader: str | None, force: bool) -> dict[str, Any]:
    content = inspect_archive(archive)
    if content.get("kind") != "mod":
        raise ContentError("The selected archive does not contain recognized mod metadata")
    report = compatibility_report(content, minecraft, loader)
    if not report["compatible"]:
        raise ContentError(json.dumps({"compatibility": report}, ensure_ascii=False))
    game_dir = resolve_game_dir(target)
    mods_dir = game_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    destination = mods_dir / archive.name
    if destination.exists() and not force:
        raise ContentError(f"Mod already exists; use --force to replace it: {destination}")
    shutil.copy2(archive, destination)
    return {"destination": str(destination), "compatibility": report, "metadata": content}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    elif isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe, launcher-agnostic Minecraft content management")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_parser = sub.add_parser("inspect", help="Inspect a ZIP/JAR without installing it")
    inspect_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    inspect_parser.add_argument("archive", type=Path)

    discover_parser = sub.add_parser("discover", help="Discover launcher instances")
    discover_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    discover_parser.add_argument("--root", action="append", type=Path, help="Additional launcher root")

    world_parser = sub.add_parser("install-world", help="Safely install a world archive")
    world_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    world_parser.add_argument("archive", type=Path)
    world_parser.add_argument("target", type=Path, help="Game directory or launcher instance")
    world_parser.add_argument("--name")

    sync_parser = sub.add_parser("sync-world", help="Copy one world to several game directories")
    sync_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    sync_parser.add_argument("source", type=Path)
    sync_parser.add_argument("--target", action="append", required=True)
    sync_parser.add_argument("--name")
    sync_parser.add_argument("--replace", action="store_true")

    mod_parser = sub.add_parser("install-mod", help="Install a compatible mod into one instance")
    mod_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    mod_parser.add_argument("archive", type=Path)
    mod_parser.add_argument("target", type=Path)
    mod_parser.add_argument("--minecraft-version")
    mod_parser.add_argument("--loader")
    mod_parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_archive(args.archive.expanduser().resolve())
        elif args.command == "discover":
            result = [asdict(item) for item in discover_instances(args.root)]
        elif args.command == "install-world":
            destination, count = extract_world(args.archive.expanduser().resolve(), resolve_game_dir(args.target) / "saves", args.name)
            result = {"destination": str(destination), "files_written": count, "verified": str(destination / "level.dat")}
        elif args.command == "sync-world":
            result = []
            for target in args.target:
                destination, count = copy_world(args.source, Path(target), args.name, args.replace)
                result.append({"destination": str(destination), "files_written": count, "verified": str(destination / "level.dat")})
        elif args.command == "install-mod":
            result = install_mod(args.archive.expanduser().resolve(), args.target, args.minecraft_version, args.loader, args.force)
        else:
            parser.error("Unknown command")
            return 2
        output(result, args.json)
        return 0
    except (ContentError, OSError, zipfile.BadZipFile) as exc:
        if args.json:
            output({"error": str(exc)}, True)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
