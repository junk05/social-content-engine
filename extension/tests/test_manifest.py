import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_v3_has_only_required_surfaces(self) -> None:
        self.assertEqual(3, self.manifest["manifest_version"])
        self.assertEqual([], self.manifest["permissions"])
        self.assertEqual(["http://127.0.0.1/*"], self.manifest["host_permissions"])
        self.assertEqual("background.js", self.manifest["background"]["service_worker"])
        self.assertEqual("options.html", self.manifest["options_ui"]["page"])

    def test_content_script_is_limited_to_threads(self) -> None:
        scripts = self.manifest["content_scripts"]
        self.assertEqual(1, len(scripts))
        self.assertEqual(
            {"https://www.threads.com/*", "https://www.threads.net/*"},
            set(scripts[0]["matches"]),
        )
        self.assertEqual(["content.js"], scripts[0]["js"])

    def test_manifest_references_existing_local_files(self) -> None:
        referenced = {
            self.manifest["background"]["service_worker"],
            self.manifest["options_ui"]["page"],
            *self.manifest["content_scripts"][0]["js"],
        }
        for relative_path in referenced:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())

    def test_no_sensitive_or_broad_permissions(self) -> None:
        forbidden = {"cookies", "webRequest", "history", "tabs", "scripting", "<all_urls>"}
        serialized = json.dumps(self.manifest, sort_keys=True)
        for permission in forbidden:
            with self.subTest(permission=permission):
                self.assertNotIn(permission, serialized)

    def test_scaffold_has_no_transport_or_dom_collection(self) -> None:
        background = (ROOT / "background.js").read_text(encoding="utf-8")
        content = (ROOT / "content.js").read_text(encoding="utf-8")
        self.assertNotIn("fetch(", background)
        self.assertNotIn("document.querySelector", content)
        self.assertNotIn("MutationObserver", content)


if __name__ == "__main__":
    unittest.main()
