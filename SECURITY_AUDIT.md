# Security audit

The original skill was designed for one local HMCL directory and trusted downloaded ZIP files more than it should. This release audits and fixes the content boundary used by the skill.

## Findings fixed

### MC-001: Archive path traversal

**Severity:** High

The old extractor accepted only POSIX separators and did not reject every normalized duplicate or link-like archive entry. A crafted archive could write outside the intended world tree on a future platform-specific path handling change, or overwrite a normalized destination unexpectedly.

**Fix:** Normalize `/` and `\\`, reject absolute paths, drive-letter paths, `..`, NUL bytes, duplicate case-folded names, encrypted members, and symlink members before writing.

### MC-002: ZIP resource exhaustion

**Severity:** High

The old extractor had no compressed-size, expanded-size, member-count, or per-member limits. A ZIP bomb could consume excessive disk space or memory during installation.

**Fix:** Enforce 512 MiB compressed input, 8 GiB total expansion, 512 MiB per member, 100,000 members, and bounded metadata reads before extraction.

### MC-003: Non-atomic world installation

**Severity:** Medium

Writing directly into a final save directory could leave a partially installed world after an interrupted or malformed extraction.

**Fix:** Extract into a temporary sibling directory, verify `level.dat`, and atomically rename the completed tree into place.

### MC-004: Cross-instance contamination

**Severity:** High

The old workflow centered on one global `mods` path and did not discover launcher instances or match the target Minecraft/loader version.

**Fix:** Discover HMCL/vanilla, Prism/MultiMC, Modrinth, CurseForge, and ATLauncher layouts; install to a selected instance; inspect Fabric, Quilt, Forge, NeoForge, CurseForge, Modrinth, and Prism metadata; fail closed on incompatible known constraints.

### MC-005: Unsafe synchronization overwrite

**Severity:** Medium

There was no multi-instance map synchronization mode or backup behavior for an existing destination.

**Fix:** Require `--replace` for an existing world, reject source symlinks, copy through a temporary tree, and create a timestamped backup before replacement.

## Residual limitations

- The installer does not execute JARs, scripts, or pack-provided commands. A downloaded world can still contain in-game command blocks or data packs; only open content from a trusted source.
- Loader-specific version expressions outside the supported common range syntax are reported as unknown and should be resolved by the launcher.
- Launcher discovery uses known local layout markers and explicit roots; a custom portable launcher path must be supplied with `--root`.
