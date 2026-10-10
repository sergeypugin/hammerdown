from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree.ElementTree import Element

MATH_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

# Load math symbols from JSON
_SYMBOLS_PATH = Path(__file__).parent / "symbols.json"
with _SYMBOLS_PATH.open("r", encoding="utf-8") as _f:
    _MATH_SYMBOLS = str.maketrans(json.load(_f))


def _math_text(text: str) -> str:
    rendered = text.translate(_MATH_SYMBOLS)
    rendered = re.sub(r"(?<=\d),(?=\d)", r"{,}", rendered)
    rendered = re.sub(r"(?:(?<![A-Za-z\\])|(?<=\\cdot))exp(?![A-Za-z])", lambda _: r"\exp", rendered)
    # Replace unescaped % with \% in LaTeX math
    parts = []
    for idx, segment in enumerate(rendered.split(r"\%")):
        parts.append(segment.replace("%", r"\%"))
    rendered = r"\%".join(parts)
    rendered = rendered.replace("\u2003", r"\quad ").replace("\u2004", " ").replace("\xa0", " ")
    # Wrap Cyrillic text in \text{...} so KaTeX/MathJax can render it inside math mode
    rendered = re.sub(r"([а-яА-ЯёЁ]+(?:\.[а-яА-ЯёЁ]+|\.)?)", r"\\text{\1}", rendered)
    return rendered


def xml_name(elem: Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def _omml_text(elem: Element | None) -> str:
    return "".join(omml_to_latex(child) for child in elem) if elem is not None else ""


def omml_to_latex(elem: Element) -> str:
    tag = xml_name(elem)
    if tag == "t":
        return _math_text(elem.text or "")
    if tag == "f":
        numerator = _omml_text(elem.find(f"{MATH_NS}num")).strip()
        denominator = _omml_text(elem.find(f"{MATH_NS}den")).strip()
        return rf"\frac{{{numerator}}}{{{denominator}}}"
    if tag in {"sSub", "sSup", "sSubSup"}:
        base = _omml_text(elem.find(f"{MATH_NS}e"))
        sub = _omml_text(elem.find(f"{MATH_NS}sub")).strip()
        sup = _omml_text(elem.find(f"{MATH_NS}sup")).strip()
        return base + (f"_{{{sub}}}" if sub else "") + (f"^{{{sup}}}" if sup else "")
    if tag == "rad":
        base = _omml_text(elem.find(f"{MATH_NS}e")).strip()
        degree = _omml_text(elem.find(f"{MATH_NS}deg")).strip()
        hidden = elem.find(f"{MATH_NS}radPr/{MATH_NS}degHide")
        if degree and hidden is None:
            return rf"\sqrt[{degree}]{{{base}}}"
        return rf"\sqrt{{{base}}}"
    if tag == "d":
        props = elem.find(f"{MATH_NS}dPr")
        begin, end = "(", ")"
        if props is not None:
            begin_elem = props.find(f"{MATH_NS}begChr")
            end_elem = props.find(f"{MATH_NS}endChr")
            if begin_elem is not None:
                begin = _math_text(begin_elem.attrib.get(f"{MATH_NS}val", begin))
            if end_elem is not None:
                end = _math_text(end_elem.attrib.get(f"{MATH_NS}val", end))
        body = " ".join(_omml_text(child) for child in elem.findall(f"{MATH_NS}e"))
        return f"{begin}{body}{end}"
    if tag == "nary":
        props = elem.find(f"{MATH_NS}naryPr")
        operator = "∑"
        if props is not None:
            operator_elem = props.find(f"{MATH_NS}chr")
            if operator_elem is not None:
                operator = operator_elem.attrib.get(f"{MATH_NS}val", operator)
        if operator == "∑":
            operator = r"\sum"
        lower = _omml_text(elem.find(f"{MATH_NS}sub")).strip()
        upper = _omml_text(elem.find(f"{MATH_NS}sup")).strip()
        body = _omml_text(elem.find(f"{MATH_NS}e"))
        return operator + (f"_{{{lower}}}" if lower else "") + (f"^{{{upper}}}" if upper else "") + (f" {body}" if body else "")
    if tag == "acc":
        props = elem.find(f"{MATH_NS}accPr")
        accent = props.find(f"{MATH_NS}chr") if props is not None else None
        value = accent.attrib.get(f"{MATH_NS}val", "") if accent is not None else ""
        body = _omml_text(elem.find(f"{MATH_NS}e")).strip()
        return rf"\bar{{{body}}}" if value == "̄" else body
    if tag == "func":
        name = _omml_text(elem.find(f"{MATH_NS}fName")).strip()
        argument = _omml_text(elem.find(f"{MATH_NS}e"))
        return f"\\{name} {argument}" if name else argument
    if tag.endswith("Pr") or tag in {"ctrlPr", "rPr"}:
        return ""
    return "".join(omml_to_latex(child) for child in elem)


def mathml_to_latex(elem: Element) -> str:
    tag = xml_name(elem)
    text = (elem.text or "").strip()
    children = list(elem)
    if tag in {"mi", "mn", "mtext"}:
        return _math_text(text)
    if tag == "mo":
        return r"\sum" if text == "∑" else _math_text(text)
    if tag == "mfrac":
        numerator = mathml_to_latex(children[0]) if children else ""
        denominator = mathml_to_latex(children[1]) if len(children) > 1 else ""
        return rf"\frac{{{numerator}}}{{{denominator}}}"
    if tag in {"msub", "msup", "msubsup"}:
        base = mathml_to_latex(children[0]) if children else ""
        sub = mathml_to_latex(children[1]) if len(children) > 1 and tag != "msup" else ""
        sup_index = 2 if tag == "msubsup" else 1
        sup = mathml_to_latex(children[sup_index]) if tag in {"msup", "msubsup"} and len(children) > sup_index else ""
        return base + (f"_{{{sub}}}" if sub else "") + (f"^{{{sup}}}" if sup else "")
    if tag in {"munder", "mover", "munderover"}:
        base = mathml_to_latex(children[0]) if children else ""
        under = mathml_to_latex(children[1]) if len(children) > 1 and tag != "mover" else ""
        over_index = 2 if tag == "munderover" else 1
        over = mathml_to_latex(children[over_index]) if tag in {"mover", "munderover"} and len(children) > over_index else ""
        operator = r"\sum" if base == "∑" else base
        return operator + (f"_{{{under}}}" if under else "") + (f"^{{{over}}}" if over else "")
    if tag == "msqrt":
        return rf"\sqrt{{{''.join(mathml_to_latex(child) for child in children)}}}"
    if tag == "mroot":
        base = mathml_to_latex(children[0]) if children else ""
        degree = mathml_to_latex(children[1]) if len(children) > 1 else ""
        return rf"\sqrt[{degree}]{{{base}}}"
    if tag == "mfenced":
        opening = elem.attrib.get("open", "(")
        closing = elem.attrib.get("close", ")")
        return opening + ", ".join(mathml_to_latex(child) for child in children) + closing
    if tag in {"math", "mrow", "mstyle", "mspace"}:
        return _math_text("".join(mathml_to_latex(child) for child in children))
    return _math_text(text + "".join(mathml_to_latex(child) for child in children))
