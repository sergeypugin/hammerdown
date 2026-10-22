from __future__ import annotations

from . import office, pdf, text, html, archive

CONVERTERS = {
    **pdf.CONVERTERS,
    **office.CONVERTERS,
    **text.CONVERTERS,
    **html.CONVERTERS,
    **archive.CONVERTERS,
}

__all__ = ["CONVERTERS"]
