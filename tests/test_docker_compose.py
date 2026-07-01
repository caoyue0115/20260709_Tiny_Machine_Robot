from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerComposeTests(unittest.TestCase):
    def test_api_publishes_local_smoke_port(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn('"8010:8010"', compose)
        self.assertNotIn('"80:8010"', compose)


if __name__ == "__main__":
    unittest.main()
