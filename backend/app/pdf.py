"""Générateur PDF minimal (texte, tableaux, traits) sans dépendance. Police Helvetica, accents via WinAnsi."""
from typing import List, Optional, Sequence, Tuple

Color = Tuple[float, float, float]

BLUE: Color = (0.098, 0.255, 0.588)
BLACK: Color = (0, 0, 0)
GRAY: Color = (0.4, 0.45, 0.5)
LIGHT: Color = (0.93, 0.94, 0.96)


def _esc(text: str) -> bytes:
    data = text.encode("cp1252", errors="replace")
    return data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def text_width(text: str, size: float, bold: bool = False) -> float:
    return len(text) * size * (0.54 if bold else 0.5)


class Pdf:
    def __init__(self, title: str = "", page_size=(595, 842), margin: int = 40):
        self.title = title
        self.width, self.height = page_size
        self.margin = margin
        self.pages: List[List[bytes]] = []
        self.y = 0.0
        self.new_page()

    # ------------------------------------------------------------ primitives
    def _ops(self) -> List[bytes]:
        return self.pages[-1]

    def new_page(self):
        self.pages.append([])
        self.y = self.height - self.margin

    def ensure(self, needed: float):
        if self.y - needed < self.margin:
            self.new_page()

    def text(self, x: float, y: float, s: str, size: float = 10, bold: bool = False, color: Color = BLACK):
        font = b"/F2" if bold else b"/F1"
        self._ops().append(
            b"BT %s %.2f Tf %.3f %.3f %.3f rg %.2f %.2f Td (" % (font, size, *color, x, y) + _esc(s) + b") Tj ET"
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5, color: Color = GRAY):
        self._ops().append(b"%.2f w %.3f %.3f %.3f RG %.2f %.2f m %.2f %.2f l S" % (width, *color, x1, y1, x2, y2))

    def rect(self, x: float, y: float, w: float, h: float, fill: Optional[Color] = None, stroke: Optional[Color] = None):
        ops = b""
        if fill:
            ops += b"%.3f %.3f %.3f rg " % fill
        if stroke:
            ops += b"%.3f %.3f %.3f RG " % stroke
        paint = b"B" if fill and stroke else (b"f" if fill else b"S")
        self._ops().append(ops + b"%.2f %.2f %.2f %.2f re %s" % (x, y, w, h, paint))

    def polyline(self, points: Sequence[Tuple[float, float]], width: float = 1.2, color: Color = BLACK):
        if len(points) < 2:
            return
        path = b"%.2f %.2f m " % points[0] + b" ".join(b"%.2f %.2f l" % p for p in points[1:])
        self._ops().append(b"%.2f w %.3f %.3f %.3f RG 1 J 1 j " % (width, *color) + path + b" S")

    # ------------------------------------------------------------ flux
    def heading(self, s: str, size: float = 16):
        self.ensure(size + 14)
        self.text(self.margin, self.y - size, s, size=size, bold=True, color=BLUE)
        self.y -= size + 10

    def paragraph(self, s: str, size: float = 10, color: Color = BLACK, bold: bool = False):
        usable = self.width - 2 * self.margin
        max_chars = max(10, int(usable / (size * (0.54 if bold else 0.5))))
        for raw in s.split("\n"):
            words, line = raw.split(" "), ""
            lines = []
            for word in words:
                candidate = f"{line} {word}".strip()
                if len(candidate) > max_chars and line:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
            for ln in lines:
                self.ensure(size + 3)
                self.text(self.margin, self.y - size, ln, size=size, color=color, bold=bold)
                self.y -= size + 3

    def spacer(self, h: float = 8):
        self.y -= h

    def key_values(self, rows: Sequence[Tuple[str, str]], size: float = 10, label_width: float = 130):
        for label, value in rows:
            self.ensure(size + 5)
            self.text(self.margin, self.y - size, label, size=size, bold=True, color=GRAY)
            self.text(self.margin + label_width, self.y - size, str(value if value is not None else "-"), size=size)
            self.y -= size + 5

    def table(self, headers: Sequence[str], rows: Sequence[Sequence], widths: Sequence[float], size: float = 8.5):
        total = sum(widths)
        scale = (self.width - 2 * self.margin) / total
        cols = [w * scale for w in widths]

        def draw_header():
            self.ensure(size + 12)
            self.rect(self.margin, self.y - size - 6, sum(cols), size + 8, fill=BLUE)
            x = self.margin
            for head, w in zip(headers, cols):
                self.text(x + 3, self.y - size - 2, head, size=size, bold=True, color=(1, 1, 1))
                x += w
            self.y -= size + 8

        draw_header()
        for index, row in enumerate(rows):
            if self.y - (size + 8) < self.margin:
                self.new_page()
                draw_header()
            if index % 2 == 0:
                self.rect(self.margin, self.y - size - 6, sum(cols), size + 8, fill=LIGHT)
            x = self.margin
            for cell, w in zip(row, cols):
                cell_text = "" if cell is None else str(cell)
                limit = max(3, int(w / (size * 0.5)) - 1)
                if len(cell_text) > limit:
                    cell_text = cell_text[: limit - 1] + "…"
                self.text(x + 3, self.y - size - 2, cell_text, size=size)
                x += w
            self.y -= size + 8
        self.y -= 6

    # ------------------------------------------------------------ sortie
    def output(self) -> bytes:
        objects: List[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

        page_ids = []
        pages_placeholder = len(objects) + 1 + 2 * len(self.pages)  # id du noeud /Pages
        for ops in self.pages:
            footer_index = len(page_ids) + 1
            stream = b"\n".join(
                ops
                + [
                    b"BT /F1 8 Tf 0.4 0.45 0.5 rg %.2f 22 Td (" % self.margin
                    + _esc(f"{self.title}  -  page {footer_index}/{len(self.pages)}")
                    + b") Tj ET"
                ]
            )
            content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            page = add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>"
                % (pages_placeholder, self.width, self.height, content, font_regular, font_bold)
            )
            page_ids.append(page)

        kids = b" ".join(b"%d 0 R" % p for p in page_ids)
        pages_id = add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids)))
        assert pages_id == pages_placeholder
        catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
        info = add(b"<< /Title (" + _esc(self.title) + b") /Producer (Fauche Gestion Outillage) >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for offset in offsets:
            out += b"%010d 00000 n \n" % offset
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF" % (
            len(objects) + 1, catalog, info, xref,
        )
        return bytes(out)
