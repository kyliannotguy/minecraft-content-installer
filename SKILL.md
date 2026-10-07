---
name: hmcl-content-installer
description: Install and synchronize Minecraft worlds, mods, shaderpacks, resource packs, and modpacks across HMCL, Prism/MultiMC, Modrinth, CurseForge, ATLauncher, and vanilla launcher instances. Use when the user downloads Minecraft content, asks for launcher or version compatibility, wants maps synchronized between instances, or needs a crash-safe content repair.
---

# Minecraft Content Installer

Use this skill for local Minecraft content management. Treat every downloaded archive as untrusted input, identify its content before copying it, and keep installs isolated to the selected launcher instance.

## Operating modes

Choose the mode from the request:

- **Install**: inspect the newest relevant download, then place it in the correct selected instance.
- **Discover**: find launcher instances and report each game directory, Minecraft version, loader, and evidence.
- **Synchronize**: copy a verified world to one or more selected game directories. Never silently delete or overwrite an existing world.
- **Compatibility**: inspect a mod or modpack manifest and compare Minecraft version, loader, and declared constraints before installation.
- **Repair**: isolate suspicious mods in the affected instance and preserve the stable profile, shaderpacks, resource packs, worlds, and backups.

## Required workflow

1. Discover instances before assuming a path. Use `scripts/minecraft_content.py discover --json`; add explicit `--root` values when a launcher stores instances elsewhere. Supported layouts include HMCL/vanilla game directories, Prism/MultiMC `instances`, Modrinth profiles, CurseForge instances, and ATLauncher instances.
2. Select the target instance from the user's request or the strongest local evidence. Do not install into a global shared `mods` directory when a per-instance directory is available.
3. Inspect the archive before installing:

   ```sh
   python3 scripts/minecraft_content.py inspect "/path/to/download.zip" --json
   ```

   Recognized kinds are `world`, `mod`, `modpack`, `shaderpack`, and `resource-pack`. A `.jar` is not automatically a mod, and a ZIP is not automatically a world.
4. Check compatibility. For a mod, compare `fabric.mod.json`, `quilt.mod.json`, `META-INF/mods.toml`, or `META-INF/neoforge.mods.toml` with the target Minecraft version and loader. For a pack, read CurseForge `manifest.json`, Modrinth `modrinth.index.json`, or Prism/MultiMC `mmc-pack.json`; preserve the pack's declared version and loader instead of guessing from its filename.
5. Install through the narrowest target:

   ```sh
   python3 scripts/minecraft_content.py install-world \
     "/path/to/map.zip" "/path/to/game-dir" --name "Readable World Name"

   python3 scripts/minecraft_content.py install-mod \
     "/path/to/mod.jar" "/path/to/game-dir" \
     --minecraft-version "1.20.1" --loader fabric
   ```

   Worlds go in `<game-dir>/saves`, shaderpacks in `<game-dir>/shaderpacks`, resource packs in `<game-dir>/resourcepacks`, and mods in the selected instance's `<game-dir>/mods`. Keep modpack archives intact for the launcher's import workflow; do not place a modpack ZIP in `mods`.
6. For map synchronization, first verify the source contains `level.dat`, then use one `--target` per selected game directory:

   ```sh
   python3 scripts/minecraft_content.py sync-world \
     "/path/to/source-world" \
     --target "/path/to/first-game-dir" \
     --target "/path/to/second-game-dir" \
     --name "Shared Parkour Map"
   ```

   Existing destinations stop the operation unless `--replace` is explicitly appropriate. Replacement creates a timestamped backup beside the destination. Do not synchronize `session.lock`, launcher metadata, or a world into an instance whose loader/modpack is incompatible without telling the user.
7. Verify the result. A world must contain `level.dat`; a mod must remain a readable JAR in the selected instance; an archive-based pack must retain its manifest. Report the exact launcher instance and path used.

## Security rules

- Use the bundled script for ZIP/JAR inspection and world extraction. It rejects absolute paths, `..` traversal, backslash traversal, duplicate normalized names, encrypted archives, excessive file counts, oversized members, and ZIP expansion beyond the safety budget.
- Do not execute files from a downloaded archive. Do not run JARs, installer binaries, scripts, or pack-provided commands as part of installation.
- Do not follow symlinks while synchronizing a world. Keep writes inside the resolved selected game directory and use temporary directories plus atomic renames.
- Do not fetch dependencies from arbitrary URLs. If a missing dependency must be downloaded, use the launcher's or a well-known official project source and verify the target Minecraft version first.
- Preserve downloaded originals and existing user data unless the user explicitly asks for cleanup. Prefer a dated backup over deletion.

## Local installation notes

The skill is launcher-agnostic and works on macOS, Windows, and Linux. A local machine may still have a known default such as `/Users/renliankun/Desktop/.minecraft`, but that path is only a fallback after discovery. On Windows, use the discovered `%APPDATA%` or `%LOCALAPPDATA%` game directory rather than assuming the macOS path. Read [references/launcher-layouts.md](references/launcher-layouts.md) for evidence-based layout detection and [references/compatibility.md](references/compatibility.md) for version/loader decisions.
