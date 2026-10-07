# Minecraft Content Installer Skill

A Codex skill for safely installing and synchronizing Minecraft maps, mods, shaderpacks, resource packs, and modpacks across HMCL, Prism/MultiMC, Modrinth, CurseForge, ATLauncher, and vanilla launcher instances.

The package includes a standard-library-only CLI that discovers instances, inspects archives, checks Minecraft/loader compatibility, extracts worlds with ZIP safety limits, and synchronizes verified worlds to multiple game directories.

Install the skill directory under `$CODEX_HOME/skills/hmcl-content-installer` or use it from a local checkout. Validate it with the bundled Codex skill validator and run `python3 -m unittest discover -s tests -v`.
