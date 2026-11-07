"""Run shared-schema and Person B offline checks from one command."""

import unittest
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    suite = unittest.TestSuite([
        unittest.TestLoader().discover(str(root / "tests")),
        unittest.TestLoader().discover(str(root / "person_b" / "tests"), top_level_dir=str(root)),
    ])
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
