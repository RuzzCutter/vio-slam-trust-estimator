#!/usr/bin/env python3
"""Math markup for the article builder.

Two layers:

* ``EQUATIONS`` – numbered display equations as Office Math (OMML) XML, so Word
  and LibreOffice show them as real formulas instead of monospaced text.
* ``split_inline`` – splits a plain sentence into runs, turning known symbols
  such as ``c(t)`` or ``d_thr`` into italic letters with real sub/superscripts.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

MATH_FONT = "Cambria Math"
TEXT_FONT = "Segoe UI"
SIZE_HALF_PT = "24"  # 12 pt
COLOR = "0F1115"


# --------------------------------------------------------------------------- #
# OMML primitives
# --------------------------------------------------------------------------- #
def _rpr(font: str, italic: bool) -> str:
    tail = "<w:i/><w:iCs/>" if italic else ""
    return (
        f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>'
        f'{tail}<w:color w:val="{COLOR}"/>'
        f'<w:sz w:val="{SIZE_HALF_PT}"/><w:szCs w:val="{SIZE_HALF_PT}"/></w:rPr>'
    )


def v(text: str) -> str:
    """Italic variable."""
    return f'<m:r>{_rpr(MATH_FONT, True)}<m:t xml:space="preserve">{escape(text)}</m:t></m:r>'


def o(text: str) -> str:
    """Upright math run: digits, operators, function names."""
    return f'<m:r>{_rpr(MATH_FONT, False)}<m:t xml:space="preserve">{escape(text)}</m:t></m:r>'


def w(text: str) -> str:
    """Ordinary words inside a formula."""
    return (
        f"<m:r><m:rPr><m:nor/></m:rPr>{_rpr(TEXT_FONT, False)}"
        f'<m:t xml:space="preserve">{escape(text)}</m:t></m:r>'
    )


def fn(text: str) -> str:
    """Function name: upright even where the renderer italicises letters."""
    return (
        f"<m:r><m:rPr><m:nor/></m:rPr>{_rpr(MATH_FONT, False)}"
        f'<m:t xml:space="preserve">{escape(text)}</m:t></m:r>'
    )


def sub(base: str, s: str) -> str:
    return f"<m:sSub><m:e>{base}</m:e><m:sub>{s}</m:sub></m:sSub>"


def sup(base: str, s: str) -> str:
    return f"<m:sSup><m:e>{base}</m:e><m:sup>{s}</m:sup></m:sSup>"


def subsup(base: str, s: str, u: str) -> str:
    return f"<m:sSubSup><m:e>{base}</m:e><m:sub>{s}</m:sub><m:sup>{u}</m:sup></m:sSubSup>"


def frac(num: str, den: str) -> str:
    return f'<m:f><m:fPr><m:type m:val="bar"/></m:fPr><m:num>{num}</m:num><m:den>{den}</m:den></m:f>'


def dlm(content: str, beg: str = "(", end: str = ")") -> str:
    return (
        f'<m:d><m:dPr><m:begChr m:val="{beg}"/><m:endChr m:val="{end}"/><m:grow/></m:dPr>'
        f"<m:e>{content}</m:e></m:d>"
    )


def bar(base: str) -> str:
    return f'<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>{base}</m:e></m:bar>'


def hat(base: str) -> str:
    return f'<m:acc><m:accPr><m:chr m:val="&#770;"/></m:accPr><m:e>{base}</m:e></m:acc>'


def nary(chrv: str, lower: str, body: str, *, lim_low: bool = True) -> str:
    loc = "undOvr" if lim_low else "subSup"
    return (
        f'<m:nary><m:naryPr><m:chr m:val="{chrv}"/><m:limLoc m:val="{loc}"/>'
        f"<m:supHide m:val=\"1\"/></m:naryPr>"
        f"<m:sub>{lower}</m:sub><m:sup/><m:e>{body}</m:e></m:nary>"
    )


def integral(body: str) -> str:
    return (
        '<m:nary><m:naryPr><m:chr m:val="&#8747;"/><m:limLoc m:val="subSup"/>'
        '<m:subHide m:val="1"/><m:supHide m:val="1"/></m:naryPr>'
        f"<m:sub/><m:sup/><m:e>{body}</m:e></m:nary>"
    )


def cases(rows: list[str]) -> str:
    body = "".join(f"<m:e>{row}</m:e>" for row in rows)
    return (
        '<m:d><m:dPr><m:begChr m:val="{"/><m:endChr m:val=""/><m:grow/></m:dPr>'
        f'<m:e><m:eqArr><m:eqArrPr><m:maxDist m:val="0"/></m:eqArrPr>{body}</m:eqArr></m:e></m:d>'
    )


def omath(body: str) -> str:
    return f"<m:oMath>{body}</m:oMath>"


# --------------------------------------------------------------------------- #
# Display equations
# --------------------------------------------------------------------------- #
_EQ = o(" = ")
_PLUS = o(" + ")
_MINUS = o(" − ")
_DOT = o(" · ")
_COMMA = o(", ")

_sigma2_pix0 = subsup(v("σ"), o("pix,0"), o("2"))
_sigma2_pix = subsup(v("σ"), o("pix"), o("2"))
_sigma2_eff = subsup(v("σ"), o("eff"), o("2")) + dlm(v("t"))
_c_of_t = v("c") + dlm(v("t"))
_d_of_t = v("d") + dlm(v("t"))
_s_of_t = v("s") + dlm(v("t"))
_d_thr = sub(v("d"), o("thr"))

EQUATIONS: dict[int, str] = {
    1: (
        sub(v("z"), v("i,c")) + _EQ + v("h") + dlm(sub(v("x"), v("t")) + _COMMA + sub(v("f"), v("i")))
        + _PLUS + sub(v("v"), v("i,c")) + o(",   ")
        + sub(v("v"), v("i,c")) + o(" ∼ ") + fn("N") + dlm(o("0") + _COMMA + _sigma2_pix + o(" ") + sub(v("I"), o("2")))
    ),
    2: sub(v("R"), o("0")) + _EQ + _sigma2_pix0 + _DOT + sub(v("I"), o("2N")),
    3: sub(v("f"), o("1")) + _EQ + frac(sub(v("N"), o("stable")), sub(v("N"), o("tracks"))),
    4: sub(v("f"), o("2")) + _EQ + fn("exp") + dlm(_MINUS + frac(sub(bar(v("e")), o("repr")), o("2"))),
    5: sub(v("f"), o("4")) + _EQ + fn("exp") + dlm(_MINUS + frac(fn("tr") + dlm(sub(v("P"), o("pos"))), sub(v("τ"), o("pos")))),
    6: (
        _c_of_t + _EQ + fn("clip") + dlm(
            frac(sub(v("f"), o("1")) + _PLUS + sub(v("f"), o("2")) + _PLUS + sub(v("f"), o("3")), o("3"))
            + _COMMA + sub(v("c"), o("min")) + _COMMA + sub(v("c"), fn("max"))
        )
    ),
    7: (
        sub(v("Δθ"), v("t")) + _EQ
        + dlm(integral(dlm(v("ω") + dlm(v("τ")) + _MINUS + sub(v("b"), o("g"))) + o(" d") + v("τ")), "‖", "‖")
    ),
    8: _d_of_t + _EQ + frac(sub(v("Δθ"), v("t")), sub(v("φ"), o("med")) + dlm(v("t")) + _PLUS + o("1")),
    9: (
        _s_of_t + _EQ + fn("clip") + dlm(
            sup(dlm(frac(sub(v("c"), o("ref")), _c_of_t + _PLUS + v("ε"))), v("p"))
            + _COMMA + o("1") + _COMMA + sub(v("s"), fn("max"))
        )
    ),
    10: _sigma2_eff + _EQ + _sigma2_pix0 + _DOT + _s_of_t,
    11: sub(v("R"), v("t")) + _EQ + _sigma2_eff + _DOT + sub(v("I"), o("2N")),
    12: v("S") + _EQ + v("H") + o(" ") + v("P") + o(" ") + sup(v("H"), o("T")) + _PLUS + sub(v("R"), v("t")),
    13: v("K") + _EQ + v("P") + o(" ") + sup(v("H"), o("T")) + o(" ") + sup(v("S"), o("−1")),
    # A lone sign in an exponent has to be a text run, otherwise the OMML to
    # StarMath import in LibreOffice drops the rest of the line.
    14: sup(hat(v("x")), fn("+")) + _EQ + sup(hat(v("x")), fn("−")) + _PLUS + v("K") + o(" ") + v("r"),
    15: sup(v("P"), fn("+")) + _EQ + dlm(v("I") + _MINUS + v("K") + o(" ") + v("H")) + o(" ") + sup(v("P"), fn("−")),
    16: (
        fn("skip") + dlm(v("t")) + _EQ + cases(
            [
                o("1") + o(",   ") + w("если ") + _d_of_t + o(" > ") + _d_thr,
                o("0") + o(",   ") + w("иначе"),
            ]
        )
    ),
    17: (
        v("C") + dlm(v("p")) + _EQ
        + frac(nary("&#8721;", v("t"), sub(v("w"), v("t")) + _DOT + _c_of_t), nary("&#8721;", v("t"), sub(v("w"), v("t"))))
    ),
    18: (
        sub(v("w"), v("t")) + _EQ + fn("exp") + dlm(
            _MINUS + frac(sup(dlm(sub(hat(v("p")), v("t")) + _MINUS + v("p")), o("2")), o("2") + sup(v("r"), o("2")))
        )
    ),
    19: (
        v("J") + _EQ + sub(v("J"), o("base")) + _PLUS + v("λ") + _DOT
        + nary("&#8721;", v("p") + o(" ∈ ") + v("Γ"), fn("max") + dlm(o("0") + _COMMA + sub(v("c"), o("th")) + _MINUS + v("C") + dlm(v("p"))))
    ),
    20: (
        sup(v("I"), o("′")) + dlm(v("x") + _COMMA + v("y")) + _EQ
        + dlm(sub(v("G"), v("σ")) + o(" ∗ ") + v("I")) + dlm(v("x") + _COMMA + v("y"))
    ),
    21: (
        sup(v("I"), o("′")) + dlm(v("x") + _COMMA + v("y")) + _EQ + fn("clip") + dlm(
            v("I") + dlm(v("x") + _COMMA + v("y")) + _DOT + dlm(o("1") + _PLUS + frac(v("p"), o("100")))
            + _COMMA + o("0") + _COMMA + o("255")
        )
    ),
}


# --------------------------------------------------------------------------- #
# Inline symbols inside ordinary sentences
# --------------------------------------------------------------------------- #
UPRIGHT_SUBS = {
    "pix", "pix,0", "0", "thr", "ref", "min", "max", "pos", "stable", "tracks",
    "repr", "eff", "base", "th", "med", "g", "2N", "2",
}

INLINE_TOKENS = [
    "v_{i,c}",
    "z_{i,c}",
    "x_t",
    "f_i",
    "f_x",
    "b_g",
    "G_σ",
    "I_2",
    "c̄",
    "G×G",
    "σ²_{pix,0}",
    "σ²_eff(t)",
    "σ²_pix",
    "σ_pix",
    "N_stable",
    "N_tracks",
    "φ_med(t)",
    "φ_med",
    "Δθ_t",
    "ē_repr",
    "J_base",
    "P_pos",
    "τ_pos",
    "d_thr",
    "c_ref",
    "c_min",
    "c_max",
    "s_max",
    "c_th",
    "R_0^{-1}",
    "R_0",
    "R_t",
    "Ω_0",
    "I_{2N}",
    "skip(t)",
    "C(x, y)",
    "c(t)",
    "d(t)",
    "s(t)",
    "C(p)",
    "p̂_t",
    "x̂⁺",
    "x̂⁻",
    "f1",
    "f2",
    "f3",
    "f4",
    "σ",
    "τ",
    "ε",
    "λ",
]

_LETTER = re.compile(r"[A-Za-z\u00C0-\u024F\u0391-\u03C9А-Яа-яЁё0-9]")
_TOKEN_RE = re.compile("|".join(re.escape(tok) for tok in sorted(INLINE_TOKENS, key=len, reverse=True)))
_ITALIC_CHARS = re.compile(r"[A-Za-z\u00C0-\u024F\u0391-\u03C9]")


FEATURE_RE = re.compile(r"^f([1-4])$")


def _parse_token(expr: str) -> list[tuple[str, str]]:
    """Turn ``d_thr`` into [('d','i'), ('thr','sub')]."""
    m = FEATURE_RE.match(expr)
    if m:
        return [("f", "i"), (m.group(1), "sub")]
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch in "_^":
            style = "sub" if ch == "_" else "sup"
            i += 1
            if i < len(expr) and expr[i] == "{":
                j = expr.index("}", i)
                body = expr[i + 1 : j]
                i = j + 1
            else:
                j = i
                while j < len(expr) and (expr[j].isalnum() or expr[j] in ",-−"):
                    j += 1
                body = expr[i:j]
                i = j
            body = body.replace("-", "−")
            italic = body not in UPRIGHT_SUBS and len(body) == 1 and bool(_ITALIC_CHARS.match(body))
            out.append((body, ("i" + style) if italic else style))
            continue
        if ch in "²³":
            out.append(("2" if ch == "²" else "3", "sup"))
            i += 1
            continue
        if ch in "⁺⁻":
            out.append(("+" if ch == "⁺" else "−", "sup"))
            i += 1
            continue
        j = i
        while j < len(expr) and _ITALIC_CHARS.match(expr[j]):
            j += 1
            # keep combining marks attached to the letter
            while j < len(expr) and expr[j] in "\u0302\u0304\u0305":
                j += 1
        if j > i:
            out.append((expr[i:j], "i"))
            i = j
            continue
        j = i
        while j < len(expr) and not _ITALIC_CHARS.match(expr[j]) and expr[j] not in "_^²³⁺⁻":
            j += 1
        out.append((expr[i:j], ""))
        i = j
    return out


_EXPLICIT_RE = re.compile(r"\$([^$]+)\$")


def split_inline(text: str) -> list[tuple[str, str]]:
    """Split a sentence into (text, style) runs; style is '', 'i', 'sub', 'sup'.

    Symbols wrapped in ``$`` are always typeset as math; the rest is matched
    against ``INLINE_TOKENS``.
    """
    if "$" in text:
        out: list[tuple[str, str]] = []
        pos = 0
        for m in _EXPLICIT_RE.finditer(text):
            if m.start() > pos:
                out.extend(split_inline(text[pos : m.start()]))
            out.extend(_parse_token(m.group(1)))
            pos = m.end()
        if pos < len(text):
            out.extend(split_inline(text[pos:]))
        return [(t, s) for t, s in out if t]
    return _split_tokens(text)


def _split_tokens(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    for m in _TOKEN_RE.finditer(text):
        start, end = m.span()
        before = text[pos:start]
        prev = text[start - 1] if start else ""
        nxt = text[end] if end < len(text) else ""
        if (prev and _LETTER.match(prev)) or (nxt and _LETTER.match(nxt)) or nxt == "_":
            continue
        if before:
            out.append((before, ""))
        out.extend(_parse_token(m.group(0)))
        pos = end
    if pos < len(text):
        out.append((text[pos:], ""))
    return [(t, s) for t, s in out if t]
