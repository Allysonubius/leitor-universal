"""Gera o ícone do aplicativo (PNG e ICO) com QPainter. Uso: python scripts/gerar_icone.py"""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

ROOT = Path(__file__).resolve().parents[1]


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#3b7cf0"))
    grad.setColorAt(1, QColor("#1f4fb8"))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    # Livro aberto
    for left in (True, False):
        path = QPainterPath()
        x0, x1 = (128 * s, 40 * s) if left else (128 * s, 216 * s)
        path.moveTo(x0, 84 * s)
        path.cubicTo((x0 + x1) / 2, 64 * s, x1, 68 * s, x1, 72 * s)
        path.lineTo(x1, 188 * s)
        path.cubicTo(x1, 184 * s, (x0 + x1) / 2, 180 * s, x0, 198 * s)
        path.closeSubpath()
        p.setBrush(QColor("#ffffff") if left else QColor("#eef3ff"))
        p.drawPath(path)
    p.setPen(QPen(QColor("#9db8ec"), max(1.0, 3 * s)))
    for i in range(4):
        y = (100 + i * 20) * s
        p.drawLine(int(58 * s), int(y), int(112 * s), int(y + 4 * s))
        p.drawLine(int(144 * s), int(y + 4 * s), int(198 * s), int(y))
    # Fita marcadora
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ff7a45"))
    ribbon = QPainterPath()
    ribbon.moveTo(170 * s, 66 * s)
    ribbon.lineTo(194 * s, 68 * s)
    ribbon.lineTo(194 * s, 128 * s)
    ribbon.lineTo(182 * s, 116 * s)
    ribbon.lineTo(170 * s, 128 * s)
    ribbon.closeSubpath()
    p.drawPath(ribbon)
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication([])
    draw(256).save(str(ROOT / "leitor_universal" / "icone.png"))
    (ROOT / "packaging").mkdir(exist_ok=True)
    draw(256).save(str(ROOT / "packaging" / "icone.ico"))
    print("ícones gerados")
