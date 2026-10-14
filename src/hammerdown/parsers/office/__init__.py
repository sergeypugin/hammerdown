from __future__ import annotations

from hammerdown.parsers.odt import convert_odt
from .legacy import convert_doc, convert_ppt, convert_xls
from .presentation import convert_pptx
from .spreadsheet import convert_xlsx
from .word import convert_docx

CONVERTERS = {
    ".docx": convert_docx,
    ".doc": convert_doc,
    ".odt": convert_odt,
    ".xlsx": convert_xlsx,
    ".xls": convert_xls,
    ".pptx": convert_pptx,
    ".ppt": convert_ppt,
}
