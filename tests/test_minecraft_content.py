from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from minecraft_content import (  # noqa: E402
    ContentError,
    compatibility_report,
    extract_world,
    inspect_archive,
    matches_constraint,
    safe_parts,
)


class MinecraftContentTests(unittest.TestCase):
    def test_safe_parts_rejects_posix_and_windows_traversal(self) -> None:
        self.assertIsNone(safe_parts("../../outside.txt"))
        self.assertIsNone(safe_parts(r"..\outside.txt"))
        self.assertIsNone(safe_parts("/absolute.txt"))
        self.assertIsNone(safe_parts("C:/absolute.txt"))
        self.assertEqual(safe_parts("world/region/r.0.0.mca"), ("world", "region", "r.0.0.mca"))

    def test_world_archive_extracts_only_the_world_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "map.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("__MACOSX/._map", b"junk")
                zf.writestr("docs/readme.txt", b"instructions")
                zf.writestr("Fancy Map/level.dat", b"level")
                zf.writestr("Fancy Map/region/r.0.0.mca", b"region")
            destination, count = extract_world(archive, root / "saves", "Parkour")
            self.assertEqual(destination.name, "Parkour")
            self.assertTrue((destination / "level.dat").is_file())
            self.assertTrue((destination / "region/r.0.0.mca").is_file())
            self.assertFalse((destination / "docs").exists())
            self.assertEqual(count, 2)

    def test_archive_path_traversal_is_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("World/level.dat", b"level")
                zf.writestr("World/../../escape.txt", b"no")
            with self.assertRaises(ContentError):
                extract_world(archive, root / "saves")
            self.assertFalse((root / "escape.txt").exists())

    def test_mod_and_pack_metadata_are_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = root / "example.jar"
            with zipfile.ZipFile(mod, "w") as zf:
                zf.writestr(
                    "fabric.mod.json",
                    json.dumps(
                        {
                            "id": "example",
                            "depends": {"minecraft": ">=1.20 <1.21", "fabricloader": ">=0.15"},
                        }
                    ),
                )
            metadata = inspect_archive(mod)
            self.assertEqual(metadata["kind"], "mod")
            self.assertIn(">=1.20 <1.21", metadata["minecraft_versions"])

            pack = root / "pack.mrpack"
            with zipfile.ZipFile(pack, "w") as zf:
                zf.writestr(
                    "modrinth.index.json",
                    json.dumps(
                        {
                            "formatVersion": 1,
                            "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.11"},
                        }
                    ),
                )
            pack_metadata = inspect_archive(pack)
            self.assertEqual(pack_metadata["kind"], "modpack")
            self.assertEqual(pack_metadata["minecraft_versions"], ["1.20.1"])

    def test_common_constraints_and_compatibility_report(self) -> None:
        self.assertTrue(matches_constraint("1.20.1", ">=1.20 <1.21"))
        self.assertFalse(matches_constraint("1.21.1", ">=1.20 <1.21"))
        self.assertTrue(matches_constraint("1.20.1", "1.20.x"))
        report = compatibility_report(
            {"minecraft_versions": [">=1.20 <1.21"], "loaders": ["fabric-loader >=0.15"]},
            "1.20.1",
            "fabric",
        )
        self.assertTrue(report["compatible"])


if __name__ == "__main__":
    unittest.main()
