# Compatibility decisions

Compatibility is a three-part check:

1. **Minecraft version**: compare the target version with the mod's declared `minecraft` dependency or the pack's manifest.
2. **Loader**: match Fabric, Quilt, Forge, or NeoForge. A loader version constraint is separate from the Minecraft version.
3. **Dependencies**: preserve required libraries such as Fabric API and pack-declared files. A mod with an unknown or missing dependency is not safe to install automatically.

## Metadata sources

- Fabric: `fabric.mod.json`, `depends.minecraft`, `depends.fabricloader`
- Quilt: `quilt.mod.json`, `quilt_loader.depends`
- Forge: `META-INF/mods.toml`
- NeoForge: `META-INF/neoforge.mods.toml`
- CurseForge pack: `manifest.json`, `minecraft.version`, `minecraft.modLoaders`
- Modrinth pack: `modrinth.index.json`, `dependencies.minecraft`, loader keys
- Prism/MultiMC pack: `mmc-pack.json`, `net.minecraft` and loader components

Treat an unknown constraint as **unknown**, not compatible by default. Exact versions are strongest evidence. Ranges such as `>=1.20 <1.21`, `1.20.x`, and simple `||` alternatives can be evaluated by the bundled script; unusual Maven or loader expressions should be reported for launcher-side resolution.

Maps can load on a newer version in some cases, but map behavior, data packs, command blocks, and custom blocks can change. When a map declares a version in its documentation, tell the user when the selected instance differs. A modded map must use the same loader and content dependencies that created its blocks or entities.
