from __future__ import annotations

from . import office, pdf, text

CONVERTERS = {
    **pdf.CONVERTERS,
    **office.CONVERTERS,
    **text.CONVERTERS,
}

__all__ = ["CONVERTERS"]
