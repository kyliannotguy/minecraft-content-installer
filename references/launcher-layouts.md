# Launcher layout detection

The launcher name is evidence, not a path convention. Prefer an explicitly selected instance and use marker files to identify its game directory.

| Launcher | Useful markers | Game directory rule |
| --- | --- | --- |
| HMCL / vanilla | `versions/`, `saves/`, `options.txt` | The directory containing `versions` and `saves` |
| Prism / MultiMC | `instance.cfg`, `mmc-pack.json` | The instance's `.minecraft` directory when present |
| Modrinth App | `modrinth.index.json`, profile metadata, `profiles/` or `instances/` | The profile's game directory |
| CurseForge | `minecraftinstance.json`, `manifest.json` | The instance directory containing `mods`, `saves`, and `config` |
| ATLauncher | `instance.json`, an `instances/` child | The instance directory |

The discovery script checks common macOS, Windows, and Linux data roots, accepts additional `--root` values, deduplicates by resolved game directory, and records evidence files. It does not scan the whole home directory or follow arbitrary links.

When a launcher has both an instance root and a nested `.minecraft`, use the nested directory for `saves`, `mods`, `shaderpacks`, and `resourcepacks`. Keep launcher metadata such as `instance.cfg`, `manifest.json`, and `mmc-pack.json` at the instance root.
