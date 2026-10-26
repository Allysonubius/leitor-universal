"""Estatísticas de leitura: metas, dias seguidos, tempo por dia e livros por mês."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QSpinBox, QVBoxLayout, QWidget,
)

from .library import Library
from .themes import Theme

MIN_SECONDS_PER_DAY = 60  # um dia conta para a sequência a partir de 1 minuto de leitura
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def reading_streak(days: dict[str, dict], today: date | None = None) -> tuple[int, int]:
    """(sequência atual, maior sequência) em dias seguidos com leitura."""
    today = today or date.today()
    active = {date.fromisoformat(d) for d, v in days.items() if v["seconds"] >= MIN_SECONDS_PER_DAY}
    current = 0
    cursor = today if today in active else today - timedelta(days=1)
    while cursor in active:
        current += 1
        cursor -= timedelta(days=1)
    longest = run = 0
    previous = None
    for day in sorted(active):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return current, longest


def finished_per_month(finished_dates: list[str], year: int) -> list[int]:
    counts = [0] * 12
    for value in finished_dates:
        try:
            d = date.fromisoformat(value[:10])
        except ValueError:
            continue
        if d.year == year:
            counts[d.month - 1] += 1
    return counts


class BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values: list[float] = []
        self.labels: list[str] = []
        self.goal: float | None = None
        self.unit = ""
        self.color = QColor("#2f6fde")
        self.color2 = QColor("#7c3aed")
        self.text_color = QColor("#666")
        self.setMinimumHeight(170)

    def set_data(self, values, labels, goal=None, unit="") -> None:
        self.values, self.labels, self.goal, self.unit = list(values), list(labels), goal, unit
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        top, bottom, left = 18, 22, 8
        chart_h = h - top - bottom
        peak = max(self.values + ([self.goal] if self.goal else []) + [1])
        n = max(len(self.values), 1)
        slot = (w - left * 2) / n
        bar_w = max(2.0, slot * 0.62)
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)
        for i, value in enumerate(self.values):
            bh = chart_h * value / peak
            x = left + i * slot + (slot - bar_w) / 2
            bar = QRectF(x, top + chart_h - max(bh, 2), bar_w, max(bh, 2))
            if value:
                grad = QLinearGradient(bar.bottomLeft(), bar.topLeft())
                grad.setColorAt(0, self.color2)
                grad.setColorAt(1, self.color)
                p.setBrush(grad)
            else:
                faint = QColor(self.color)
                faint.setAlpha(50)
                p.setBrush(faint)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(bar, 3, 3)
            if self.labels and (n <= 12 or i % 5 == 0 or i == n - 1):
                p.setPen(self.text_color)
                p.drawText(QRectF(x - 12, h - bottom + 4, bar_w + 24, 14), Qt.AlignCenter, self.labels[i])
            if n <= 12 and value:
                p.setPen(self.text_color)
                p.drawText(QRectF(x - 12, top + chart_h - bh - 15, bar_w + 24, 14), Qt.AlignCenter, f"{value:g}")
        if self.goal:
            y = top + chart_h - chart_h * self.goal / peak
            pen = QPen(QColor("#e0802a"), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(left, int(y), w - left, int(y))
            p.drawText(QRectF(w - 120, y - 15, 112, 14), Qt.AlignRight, f"meta {self.goal:g} {self.unit}")
        p.end()


class StatCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.title = QLabel(title)
        self.title.setObjectName("muted")
        self.value = QLabel("—")
        self.value.setStyleSheet("font-size: 26px; font-weight: 700;")
        self.detail = QLabel()
        self.detail.setObjectName("muted")
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)


class StatsView(QWidget):
    def __init__(self, library: Library, theme: Theme, parent=None):
        super().__init__(parent)
        self.library = library
        heading = QLabel("Estatísticas de leitura")
        heading.setObjectName("heading")

        self.card_today = StatCard("Hoje")
        self.card_streak = StatCard("Dias seguidos lendo")
        self.card_year = StatCard(f"Livros concluídos em {date.today().year}")
        self.card_total = StatCard("Tempo total de leitura")
        cards = QGridLayout()
        for i, card in enumerate((self.card_today, self.card_streak, self.card_year, self.card_total)):
            cards.addWidget(card, 0, i)
        self.daily_progress = QProgressBar()
        self.daily_progress.setTextVisible(True)
        self.year_progress = QProgressBar()
        self.year_progress.setTextVisible(True)

        self.daily_goal = QSpinBox()
        self.daily_goal.setRange(5, 600)
        self.daily_goal.setSuffix(" min por dia")
        self.daily_goal.setValue(int(library.setting("meta_diaria_min", "20")))
        self.daily_goal.valueChanged.connect(lambda v: self._save_goal("meta_diaria_min", v))
        self.year_goal = QSpinBox()
        self.year_goal.setRange(1, 365)
        self.year_goal.setSuffix(" livros por ano")
        self.year_goal.setValue(int(library.setting("meta_anual_livros", "12")))
        self.year_goal.valueChanged.connect(lambda v: self._save_goal("meta_anual_livros", v))
        goals = QGridLayout()
        goals.addWidget(QLabel("Meta diária:"), 0, 0)
        goals.addWidget(self.daily_goal, 0, 1)
        goals.addWidget(self.daily_progress, 0, 2)
        goals.addWidget(QLabel("Meta do ano:"), 1, 0)
        goals.addWidget(self.year_goal, 1, 1)
        goals.addWidget(self.year_progress, 1, 2)
        goals.setColumnStretch(2, 1)

        self.days_chart = BarChart()
        self.months_chart = BarChart()
        days_title = QLabel("<b>Minutos lidos nos últimos 30 dias</b>")
        months_title = QLabel(f"<b>Livros concluídos por mês em {date.today().year}</b>")
        charts = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(days_title)
        left.addWidget(self.days_chart, 1)
        right.addWidget(months_title)
        right.addWidget(self.months_chart, 1)
        charts.addLayout(left, 3)
        charts.addLayout(right, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(14)
        layout.addWidget(heading)
        layout.addLayout(cards)
        layout.addLayout(goals)
        layout.addLayout(charts, 1)
        self.set_theme(theme)

    def set_theme(self, theme: Theme) -> None:
        for chart in (self.days_chart, self.months_chart):
            chart.color = QColor(theme.accent)
            chart.color2 = QColor(theme.accent2)
            chart.text_color = QColor(theme.muted)
            chart.update()

    def _save_goal(self, key: str, value: int) -> None:
        self.library.set_setting(key, str(value))
        self.refresh()

    def refresh(self) -> None:
        days = self.library.daily_reading()
        today = date.today()
        today_min = days.get(today.isoformat(), {}).get("seconds", 0) // 60
        today_pages = days.get(today.isoformat(), {}).get("pages", 0)
        current, longest = reading_streak(days, today)
        finished = finished_per_month(self.library.finished_dates(), today.year)
        # O registro diário existe desde a 1.3.0; o total por livro cobre o tempo anterior.
        total_seconds = max(self.library.stats()["seconds"], sum(d["seconds"] for d in days.values()))
        daily_goal, year_goal = self.daily_goal.value(), self.year_goal.value()

        self.card_today.value.setText(f"{today_min} min")
        self.card_today.detail.setText(f"{today_pages} página(s)")
        self.card_streak.value.setText(f"{current} dia(s)")
        self.card_streak.detail.setText(f"Recorde: {longest} dia(s)")
        self.card_year.value.setText(str(sum(finished)))
        self.card_year.detail.setText(f"Meta: {year_goal}")
        self.card_total.value.setText(f"{total_seconds / 3600:.1f} h")
        self.card_total.detail.setText(f"{len([d for d in days.values() if d['seconds'] >= 60])} dia(s) com leitura")

        self.daily_progress.setRange(0, daily_goal)
        self.daily_progress.setValue(min(today_min, daily_goal))
        self.daily_progress.setFormat(f"{today_min} de {daily_goal} min hoje")
        self.year_progress.setRange(0, year_goal)
        self.year_progress.setValue(min(sum(finished), year_goal))
        self.year_progress.setFormat(f"{sum(finished)} de {year_goal} livros")

        last30 = [today - timedelta(days=29 - i) for i in range(30)]
        self.days_chart.set_data([days.get(d.isoformat(), {}).get("seconds", 0) // 60 for d in last30],
                                 [f"{d.day:02d}/{d.month:02d}" for d in last30], goal=daily_goal, unit="min")
        self.months_chart.set_data(finished, MONTHS)
