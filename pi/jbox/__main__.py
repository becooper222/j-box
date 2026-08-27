import logging
from pathlib import Path

from .app import JBoxApp
from .config import load

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

cfg = load(Path(__file__).resolve().parent.parent / "config.yaml")
JBoxApp(cfg).run()
