"""注册机入口：python -m registrar。"""
from __future__ import annotations

import sys

from registrar.cli import main

if __name__ == "__main__":
    sys.exit(main())
