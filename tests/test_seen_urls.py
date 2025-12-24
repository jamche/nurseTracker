import json
import tempfile
import unittest
from pathlib import Path

from utils.state import read_seen_urls, write_seen_urls


class TestSeenUrls(unittest.TestCase):
    def test_seen_urls_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "seen.json"
            write_seen_urls(path, {"b", "a", "a", "  "})
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw, ["a", "b"])
            self.assertEqual(read_seen_urls(path), {"a", "b"})
