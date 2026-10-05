"""Draw the SinhalaSubs icon and save it as .ico (all Windows sizes) and .png.

Run:  .venv\\Scripts\\python tools\\make_icon.py
"""

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

OUT = Path(__file__).resolve().parent.parent / "sinhalasubs" / "data"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    s = size / 256

    # warm gold tile with rounded corners
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 56 * s, 56 * s)
    p.fillPath(tile, QColor("#E8A33D"))

    # the Sinhala letter "සි"
    f = QFont("Nirmala UI")
    f.setPixelSize(round(150 * s))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#1A1206"))
    p.drawText(QRectF(0, 6 * s, 256 * s, 170 * s), Qt.AlignCenter, "සි")

    # two caption bars under it
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1A1206"))
    p.drawRoundedRect(QRectF(52 * s, 178 * s, 152 * s, 22 * s), 11 * s, 11 * s)
    p.setBrush(QColor(26, 18, 6, 140))
    p.drawRoundedRect(QRectF(82 * s, 208 * s, 92 * s, 16 * s), 8 * s, 8 * s)
    p.end()
    return img


def main() -> None:
    app = QGuiApplication([])  # noqa: F841 - fonts need a Qt application
    OUT.mkdir(parents=True, exist_ok=True)
    draw(256).save(str(OUT / "icon.png"))
    # Qt's ICO writer stores one image per call, so build the multi-size file by hand
    import struct
    from io import BytesIO

    from PySide6.QtCore import QBuffer, QIODevice
    images = []
    for n in (16, 24, 32, 48, 64, 128, 256):
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        draw(n).save(buf, "PNG")
        images.append((n, bytes(buf.data())))
    out = BytesIO()
    out.write(struct.pack("<HHH", 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    for n, data in images:
        out.write(struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    for _, data in images:
        out.write(data)
    (OUT / "icon.ico").write_bytes(out.getvalue())
    print("saved", OUT / "icon.ico")


if __name__ == "__main__":
    main()
