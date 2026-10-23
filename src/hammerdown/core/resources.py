from __future__ import annotations

import base64
import logging
import mimetypes
import os
import sys
from pathlib import Path

logger = logging.getLogger("hammerdown")


def embed_temporary_resources(markdown: str, temporary_dir: Path) -> str:
    """Inline every file from a temporary directory as a base64 data URI."""
    resources: dict[str, str] = {}
    for resource in temporary_dir.rglob("*"):
        if not resource.is_file():
            continue
        relative = resource.relative_to(temporary_dir).as_posix()
        mime_type = mimetypes.guess_type(resource.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(resource.read_bytes()).decode("ascii")
        resources[relative] = f"data:{mime_type};base64,{encoded}"

    embedded = markdown
    for relative, data_uri in sorted(resources.items(), key=lambda item: len(item[0]), reverse=True):
        embedded = embedded.replace(relative, data_uri)
        embedded = embedded.replace(relative.replace("/", "\\"), data_uri)
    return embedded


def token_count(markdown: str) -> int:
    """Count tokens with tiktoken, falling back to 0 when unavailable."""
    try:
        if getattr(sys, "frozen", False) and not os.environ.get("TIKTOKEN_CACHE_DIR"):
            bundle_dir = getattr(sys, "_MEIPASS", None)
            bundled_cache = Path(bundle_dir) / "data-gym-cache" if bundle_dir else None
            if bundled_cache and bundled_cache.is_dir():
                os.environ["TIKTOKEN_CACHE_DIR"] = str(bundled_cache)

        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(markdown, disallowed_special=()))
    except Exception as exc:
        logger.warning("Token counting unavailable: %s", exc)
        return 0
