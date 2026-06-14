import sys
from pathlib import Path

# repo root on path so `accelerator` and `bench` import under pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
