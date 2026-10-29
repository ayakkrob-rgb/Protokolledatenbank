"""Kleiner, abhängigkeitsfreier PDF-Generator für Text-Protokolle sowie
Kennzeichnung („Wasserzeichen“) bestehender PDF-Dateien mit pypdf.

Bewusst einfach gehalten: Standardschrift Helvetica (WinAnsi-Kodierung),
automatischer Zeilen- und Seitenumbruch, Kopf- und Fußzeilen.
"""
import io
import logging
import zlib

logger = logging.getLogger(__name__)

A4 = (595.28, 841.89)

# Zeichenbreiten der Helvetica (in 1/1000 em) laut Adobe-AFM
_WIDTHS = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191, "(": 333, ")": 333,
    "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "<": 584, "=": 584,
    ">": 584, "?": 556, "@": 1015, "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667, "Q": 778,
    "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611, "[": 278,
    "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333, "a": 556, "b": 556, "c": 500, "d": 556, "e": 556,
    "f": 278, "g": 556, "h": 556, "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556, "o": 556,
    "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500, "w": 722, "x": 500, "y": 500,
    "z": 500, "{": 334, "|": 260, "}": 334, "~": 584, "Ä": 667, "Ö": 778, "Ü": 722, "ß": 611, "€": 556,
    "–": 556, "—": 1000, "„": 333, "“": 333, "”": 333, "‚": 222, "‘": 222, "’": 222, "•": 350, "…": 1000,
    "°": 400, "§": 556, "µ": 556, "×": 584, "±": 584, "·": 278, "²": 333, "³": 333, "½": 834, "¼": 834,
}
for _digit in "0123456789":
    _WIDTHS[_digit] = 556

# Zeichen außerhalb von WinAnsi, die in medizinischen Texten häufig vorkommen
_REPLACEMENTS = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "κ": "kappa", "λ": "lambda",
    "μ": "µ", "π": "pi", "σ": "sigma", "τ": "tau", "ω": "omega", "Δ": "Delta", "→": "->", "←": "<-",
    "↔": "<->", "⇒": "=>", "↑": "^", "↓": "v", "≥": ">=", "≤": "<=", "≈": "~", "≠": "!=", "✓": "x",
    "\t": "    ", "\u00a0": " ", "\u2009": " ", "\u202f": " ",
}


def _normalize(text):
    return "".join(_REPLACEMENTS.get(ch, ch) for ch in text)


def _encode(text):
    raw = _normalize(text).encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").replace(b"\r", b"")


def text_width(text, size, bold=False):
    width = sum(_WIDTHS.get(ch, 556) for ch in _normalize(text)) * size / 1000
    return width * (1.06 if bold else 1.0)


def wrap_text(text, size, max_width, bold=False):
    """Bricht einen Absatz in Zeilen um, die höchstens ``max_width`` breit sind."""
    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        indent = len(paragraph) - len(paragraph.lstrip(" "))
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = " " * indent
        for word in words:
            candidate = f"{current} {word}" if current.strip() else current + word
            if text_width(candidate, size, bold) <= max_width:
                current = candidate
                continue
            if current.strip():
                lines.append(current)
            # Sehr lange Wörter (z. B. URLs) hart umbrechen
            while text_width(word, size, bold) > max_width:
                cut = len(word)
                while cut > 1 and text_width(word[:cut], size, bold) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


def _num(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


class _Page:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.ops = []

    def text(self, x, y, text, size=11, bold=False, gray=0.0):
        font = "F2" if bold else "F1"
        self.ops.append(
            b"BT /" + font.encode() + b" " + _num(size).encode() + b" Tf "
            + _num(gray).encode() + b" g " + _num(x).encode() + b" " + _num(y).encode()
            + b" Td (" + _encode(text) + b") Tj ET"
        )

    def rotated_text(self, x, y, angle_cos, angle_sin, text, size, gray=0.5, alpha_state=True):
        self.ops.append(
            b"q " + (b"/GS1 gs " if alpha_state else b"") + b"BT /F2 " + _num(size).encode() + b" Tf "
            + _num(gray).encode() + b" g "
            + " ".join(_num(v) for v in (angle_cos, angle_sin, -angle_sin, angle_cos, x, y)).encode()
            + b" Tm (" + _encode(text) + b") Tj ET Q"
        )

    def line(self, x1, y1, x2, y2, gray=0.8, width=0.6):
        self.ops.append(
            f"q {_num(gray)} G {_num(width)} w {_num(x1)} {_num(y1)} m {_num(x2)} {_num(y2)} l S Q".encode()
        )

    def stream(self):
        return b"\n".join(self.ops)


def _build_pdf(pages, title=""):
    objects = {}

    def put(obj_id, body):
        objects[obj_id] = body

    put(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    put(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    put(5, b"<< /Type /ExtGState /ca 0.12 /CA 0.12 >>")
    resources = b"<< /Font << /F1 3 0 R /F2 4 0 R >> /ExtGState << /GS1 5 0 R >> >>"
    next_id = 6
    kids = []
    for page in pages:
        content_id, page_id = next_id, next_id + 1
        next_id += 2
        data = zlib.compress(page.stream())
        put(content_id, b"<< /Length " + str(len(data)).encode() + b" /Filter /FlateDecode >>\nstream\n" + data + b"\nendstream")
        put(
            page_id,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + _num(page.width).encode() + b" "
            + _num(page.height).encode() + b"] /Resources " + resources
            + b" /Contents " + str(content_id).encode() + b" 0 R >>",
        )
        kids.append(page_id)
    put(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    put(2, b"<< /Type /Pages /Kids [" + b" ".join(f"{k} 0 R".encode() for k in kids) + b"] /Count " + str(len(kids)).encode() + b" >>")
    info_id = next_id
    put(info_id, b"<< /Title (" + _encode(title) + b") /Producer (Protokolldatenbank) >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = out.tell()
        out.write(f"{obj_id} 0 obj\n".encode() + objects[obj_id] + b"\nendobj\n")
    xref_pos = out.tell()
    size = max(objects) + 1
    out.write(f"xref\n0 {size}\n0000000000 65535 f \n".encode())
    for obj_id in range(1, size):
        out.write(f"{offsets[obj_id]:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {size} /Root 1 0 R /Info {info_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())
    return out.getvalue()


def render_text_pdf(title, meta_lines, body, footer_text="", diagonal_text=""):
    """Erzeugt ein mehrseitiges A4-PDF mit Titel, Metadaten und Fließtext."""
    width, height = A4
    margin_x, margin_top, margin_bottom = 56, 64, 60
    usable = width - 2 * margin_x
    body_size, leading = 10.5, 15

    pages = []

    def new_page():
        page = _Page(width, height)
        pages.append(page)
        return page, height - margin_top

    page, y = new_page()
    for line in wrap_text(title, 17, usable, bold=True):
        page.text(margin_x, y, line, size=17, bold=True)
        y -= 22
    y -= 2
    for meta in meta_lines:
        for line in wrap_text(meta, 9.5, usable):
            page.text(margin_x, y, line, size=9.5, gray=0.35)
            y -= 13
    y -= 4
    page.line(margin_x, y, width - margin_x, y)
    y -= 22

    for line in wrap_text(body or "", body_size, usable):
        if y < margin_bottom + 10:
            page, y = new_page()
        page.text(margin_x, y, line, size=body_size)
        y -= leading

    total = len(pages)
    for number, pg in enumerate(pages, start=1):
        if diagonal_text:
            size = max(14, min(36, width / max(len(diagonal_text), 1) * 1.6))
            tw = text_width(diagonal_text, size, bold=True)
            pg.rotated_text(width / 2 - tw * 0.7071 / 2, height / 2 - tw * 0.7071 / 2, 0.7071, 0.7071, diagonal_text, size)
        pg.line(margin_x, 42, width - margin_x, 42, gray=0.85)
        label = f"Seite {number} von {total}"
        pg.text(width - margin_x - text_width(label, 8), 30, label, size=8, gray=0.45)
        if footer_text:
            for i, line in enumerate(wrap_text(footer_text, 8, usable - 70)[:2]):
                pg.text(margin_x, 30 - i * 10, line, size=8, gray=0.45)
    return _build_pdf(pages, title=title)


def _overlay(width, height, x0, y0, footer_text, diagonal_text):
    page = _Page(width, height)
    margin = 18
    footer = footer_text
    size = 7
    while text_width(footer, size) > width - 2 * margin and size > 4:
        size -= 0.5
    page.text(x0 + margin, y0 + 10, footer, size=size, gray=0.45)
    if diagonal_text:
        diag_size = max(14, min(36, width / max(len(diagonal_text), 1) * 1.6))
        cos = sin = 0.7071
        tw = text_width(diagonal_text, diag_size, bold=True)
        cx, cy = x0 + width / 2, y0 + height / 2
        page.rotated_text(cx - tw * cos / 2, cy - tw * sin / 2, cos, sin, diagonal_text, diag_size)
    return _build_pdf([page])


def stamp_pdf(data, footer_text, diagonal_text=""):
    """Versieht jede Seite eines PDFs mit einer Fußzeile (und optional einem
    diagonalen Schriftzug). Bei Problemen wird das Original zurückgegeben."""
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            if not reader.decrypt(""):
                return data
        writer = PdfWriter()
        cache = {}
        for page in reader.pages:
            box = page.cropbox
            key = (float(box.left), float(box.bottom), float(box.width), float(box.height))
            if key not in cache:
                overlay_bytes = _overlay(key[2], key[3], key[0], key[1], footer_text, diagonal_text)
                cache[key] = PdfReader(io.BytesIO(overlay_bytes)).pages[0]
            page.merge_page(cache[key])
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001 – im Zweifel lieber das Original ausliefern
        logger.exception("PDF konnte nicht gekennzeichnet werden")
        return data
