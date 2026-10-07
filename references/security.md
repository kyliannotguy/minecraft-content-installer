# Security audit baseline

The installer handles untrusted ZIP/JAR files and writes into user-controlled game directories. The implementation must preserve these invariants:

- Normalize both `/` and `\\` before checking archive paths; reject absolute paths, drive-letter paths, `..`, NUL bytes, duplicate case-folded names, and metadata junk.
- Preflight compressed size, uncompressed size, member size, and member count to limit ZIP bomb resource exhaustion.
- Never execute archive contents. Reading JSON/TOML metadata is sufficient for classification.
- Extract into a temporary sibling directory and atomically rename only after `level.dat` is present.
- Never follow source symlinks during world synchronization. Back up an existing destination before replacement.
- Keep compatibility checks fail-closed when a version or loader cannot be understood.
- Avoid logging credentials, launcher tokens, or full private configuration files. Evidence paths may be shown, but secrets must not be copied into reports.

The safety limits are intentionally finite defaults. A future caller can adjust them in code for a controlled local archive, but the normal skill workflow should not weaken them to accept an unknown download.
