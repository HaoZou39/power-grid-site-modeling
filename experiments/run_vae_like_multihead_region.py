from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithms.vae_like_multihead.vae_like_multihead_main import main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run VAE-like multi-head region optimization.")
    parser.add_argument("--config", default="config/default_config.json")
    parser.add_argument("--output-dir", default="outputs/vae_like_multihead_region")
    args = parser.parse_args()
    main(args.config, args.output_dir)
