"""Centralized AI prompt loader.

All LLM system prompts live as plain-text .txt files in this directory.
Use ``load_prompt(name)`` to read one by stem name (without extension).
"""

from __future__ import annotations

import functools
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent


@functools.lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    """Return the contents of ``<prompts_dir>/<name>.txt``.

    Cached after first read so disk I/O only happens once per process.
    Raises ``FileNotFoundError`` with a helpful message if the file is missing.
    """
    path = _PROMPT_DIR / f"{name}.txt"
    if not path.exists():
        available = sorted(p.stem for p in _PROMPT_DIR.glob("*.txt"))
        raise FileNotFoundError(f"Prompt '{name}' not found at {path}. Available: {available}")
    return path.read_text(encoding="utf-8").strip()
