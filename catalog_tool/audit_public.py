"""Compatibility entry for the repository-wide publication check."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.audit_public import audit


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    sys.exit(0 if result["ok"] else 1)
