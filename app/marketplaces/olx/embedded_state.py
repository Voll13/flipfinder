"""Generic decoding of OLX's embedded pre-rendered state."""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from app.exceptions import ScraperError


_STATE_RE = re.compile(r'window\.__PRERENDERED_STATE__\s*=\s*("(?:\\.|[^"\\])*")\s*;', re.S)


def extract_prerendered_state(html: str) -> dict[str, Any]:
    """Decode the source-preserved OLX state without making a network request."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.select_one("script#olx-init-config")
    # Chrome's View Source save turns source lines into table cells.  Reading
    # page text preserves the original assignment for that local-file format.
    source = script.get_text() if script else soup.get_text()
    match = _STATE_RE.search(source)
    if not match:
        raise ScraperError("OLX __PRERENDERED_STATE__ assignment is missing")
    try:
        state = json.loads(json.loads(match.group(1)))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ScraperError("OLX __PRERENDERED_STATE__ is not valid JSON") from exc
    if not isinstance(state, dict):
        raise ScraperError("OLX __PRERENDERED_STATE__ must decode to an object")
    return state
