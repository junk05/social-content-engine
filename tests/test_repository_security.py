import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import validate_repo


class RepositorySecurityTest(unittest.TestCase):
    def test_secret_scan_covers_shell_env_examples_and_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run.sh").write_text(
                "export API_KEY=" + "x" * 24 + "\n", encoding="utf-8"
            )
            (root / ".env.example").write_text(
                "THREADS_ACCESS_TOKEN=" + "y" * 24 + "\n", encoding="utf-8"
            )
            errors = []
            with patch.object(validate_repo, "ROOT", root):
                validate_repo.scan_secrets(errors)
            self.assertEqual(
                [
                    "possible committed secret: .env.example",
                    "possible committed secret: run.sh",
                ],
                sorted(errors),
            )

    def test_secret_scan_allows_empty_examples_and_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text(
                "THREADS_ACCESS_TOKEN=\nOPENAI_API_KEY='...'\n", encoding="utf-8"
            )
            errors = []
            with patch.object(validate_repo, "ROOT", root):
                validate_repo.scan_secrets(errors)
            self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
