"""pytest path 引导：让 tests 能 import src 下的 thesis_watch 包。"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
