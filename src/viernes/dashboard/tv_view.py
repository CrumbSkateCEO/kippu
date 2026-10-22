"""Dashboard HUD cinematográfico para el monitor secundario (TV)."""

from __future__ import annotations

import datetime as _dt
import logging
import math
import sys

import cv2
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class Palette:
    BG_DEEP = QColor(4, 8, 14)
    BG_PANEL = QColor(8, 16, 28)
    HUD_CYAN = QColor(64, 224, 255)
    HUD_CYAN_SOFT = QColor(64, 224, 255, 70)
    HUD_AMBER = QColor(255, 184, 72)
    HUD_GREEN = QColor(72, 255, 186)
    HUD_RED = QColor(255, 86, 110)
    HUD_DIM = QColor(64, 224, 255, 55)
    GOLD = QColor(212, 176, 112)
    TEXT_MAIN = QColor(232, 244, 255)
    TEXT_MUTED = QColor(140, 168, 188)
    GLASS = QColor(6, 14, 24, 180)
    SCAN = QColor(120, 210, 255, 18)


class ViernesState:
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


def _mono(size: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    font = QFont()
    font.setFamilies(["JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"])
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
    return font


def _sans(size: int, weight: QFont.Weight = QFont.Weight.Medium) -> QFont:
    font = QFont()
    font.setFamilies(["Inter", "Segoe UI", "Noto Sans", "DejaVu Sans", "sans-serif"])
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


def _state_color(state: str) -> QColor:
    return {
        ViernesState.LISTENING: Palette.HUD_CYAN,
        ViernesState.THINKING: Palette.HUD_AMBER,
        ViernesState.SPEAKING: Palette.HUD_GREEN,
        ViernesState.ERROR: Palette.HUD_RED,
    }.get(state, Palette.HUD_DIM)


class Atmosphere(QWidget):
    """Fondo con viñeta, retícula y un pulso ambiental muy suave."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(80)

    def _tick(self):
        self._pulse += 0.04
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor(6, 12, 22))
        bg.setColorAt(0.45, QColor(3, 7, 13))
        bg.setColorAt(1.0, QColor(2, 4, 8))
        painter.fillRect(self.rect(), bg)

        glow = QRadialGradient(QPointF(w * 0.5, h * 0.18), max(w, h) * 0.55)
        pulse = 28 + int(10 * math.sin(self._pulse))
        glow.setColorAt(0.0, QColor(20, 70, 110, pulse))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), glow)

        painter.setPen(QPen(QColor(40, 90, 130, 28), 1))
        step = 48
        for x in range(0, w, step):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, step):
            painter.drawLine(0, y, w, y)

        painter.setPen(QPen(Palette.SCAN, 1))
        for y in range(0, h, 4):
            painter.drawLine(0, y, w, y)

        vignette = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.72)
        vignette.setColorAt(0.55, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 140))
        painter.fillRect(self.rect(), vignette)
        painter.end()


class ArcReactorIndicator(QWidget):
    """Núcleo orbital con anillos, ticks y glow según el estado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 132)
        self._rotation = 0.0
        self._pulse = 0.0
        self._color = Palette.HUD_CYAN
        self._speed = 2.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(33)

    def set_state(self, state: str):
        self._color = _state_color(state)
        self._speed = {
            ViernesState.LISTENING: 3.4,
            ViernesState.THINKING: 11.0,
            ViernesState.SPEAKING: 6.2,
            ViernesState.ERROR: 8.0,
        }.get(state, 1.2)

    def _animate(self):
        self._rotation = (self._rotation + self._speed) % 360
        self._pulse += 0.12
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        painter.translate(cx, cy)

        pulse = 0.55 + 0.45 * math.sin(self._pulse)
        glow = QRadialGradient(QPointF(0, 0), 58)
        g = QColor(self._color)
        g.setAlpha(int(28 + 50 * pulse))
        glow.setColorAt(0.0, g)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), 58, 58)

        painter.save()
        painter.rotate(self._rotation)
        tick = QPen(self._color, 1.6)
        painter.setPen(tick)
        for i in range(24):
            painter.drawLine(QPointF(0, -54), QPointF(0, -48 if i % 3 else -44))
            painter.rotate(15)
        painter.restore()

        ring = QConicalGradient(QPointF(0, 0), -self._rotation)
        c = QColor(self._color)
        c_soft = QColor(self._color)
        c_soft.setAlpha(20)
        ring.setColorAt(0.0, c)
        ring.setColorAt(0.35, c_soft)
        ring.setColorAt(0.7, c)
        ring.setColorAt(1.0, c_soft)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(ring), 3.2))
        painter.drawEllipse(QPointF(0, 0), 40, 40)

        painter.save()
        painter.rotate(-self._rotation * 1.45)
        dashed = QPen(self._color, 2.4)
        dashed.setDashPattern([10, 6, 2, 6])
        painter.setPen(dashed)
        painter.drawEllipse(QPointF(0, 0), 28, 28)
        painter.restore()

        core = QRadialGradient(QPointF(-3, -3), 14)
        core.setColorAt(0.0, QColor(255, 255, 255, 220))
        core.setColorAt(0.45, self._color)
        core.setColorAt(1.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 40))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(core)
        painter.drawEllipse(QPointF(0, 0), 11, 11)
        painter.end()


class SignalBars(QWidget):
    """Ecualizador decorativo ligado al estado de voz."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(92, 42)
        self._phase = 0.0
        self._energy = 0.22
        self._color = Palette.HUD_CYAN
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(40)

    def set_state(self, state: str):
        self._color = _state_color(state)
        self._energy = {
            ViernesState.LISTENING: 0.55,
            ViernesState.THINKING: 0.85,
            ViernesState.SPEAKING: 0.95,
            ViernesState.ERROR: 0.4,
        }.get(state, 0.18)

    def _tick(self):
        self._phase += 0.22
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = 9
        gap = 3
        bw = (self.width() - gap * (n - 1)) / n
        for i in range(n):
            wave = 0.25 + 0.75 * abs(math.sin(self._phase + i * 0.55))
            h = max(4, self.height() * self._energy * wave)
            x = i * (bw + gap)
            y = self.height() - h
            color = QColor(self._color)
            color.setAlpha(90 + int(140 * wave * self._energy))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, y, bw, h), 2, 2)
        painter.end()


class ViewportChrome(QWidget):
    """Marcos, cruces de enfoque y etiquetas sobre el vídeo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = Palette.HUD_CYAN
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_color(self, color: QColor):
        self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        inset = 18
        c = 28
        x0, y0, x1, y1 = inset, inset, w - inset, h - inset

        path = QPainterPath()
        path.moveTo(x0 + c, y0)
        path.lineTo(x1 - c, y0)
        path.lineTo(x1, y0 + c)
        path.lineTo(x1, y1 - c)
        path.lineTo(x1 - c, y1)
        path.lineTo(x0 + c, y1)
        path.lineTo(x0, y1 - c)
        path.lineTo(x0, y0 + c)
        path.closeSubpath()

        fill = QColor(self._color)
        fill.setAlpha(12)
        painter.setBrush(fill)
        painter.setPen(QPen(self._color, 1.8))
        painter.drawPath(path)

        inner = QColor(self._color)
        inner.setAlpha(90)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(inner, 1))
        painter.drawRect(QRectF(x0 + 10, y0 + 10, (x1 - x0) - 20, (y1 - y0) - 20))

        L = 26
        bold = QPen(self._color, 3.2)
        painter.setPen(bold)
        painter.drawLine(x0, y0 + c, x0 + L, y0 + c)
        painter.drawLine(x0 + c, y0, x0 + c, y0 + L)
        painter.drawLine(x1, y0 + c, x1 - L, y0 + c)
        painter.drawLine(x1 - c, y0, x1 - c, y0 + L)
        painter.drawLine(x0, y1 - c, x0 + L, y1 - c)
        painter.drawLine(x0 + c, y1, x0 + c, y1 - L)
        painter.drawLine(x1, y1 - c, x1 - L, y1 - c)
        painter.drawLine(x1 - c, y1, x1 - c, y1 - L)

        painter.setFont(_mono(11))
        painter.setPen(self._color)
        painter.drawText(QRectF(x0 + 18, y0 + 14, 220, 20), Qt.AlignmentFlag.AlignLeft, "OPTICAL FEED  ·  CAM-01")
        painter.drawText(QRectF(x1 - 210, y0 + 14, 192, 20), Qt.AlignmentFlag.AlignRight, "SECURE LINK")
        painter.setPen(Palette.GOLD)
        painter.drawText(QRectF(x0 + 18, y1 - 36, 180, 20), Qt.AlignmentFlag.AlignLeft, "●  LIVE")
        painter.setPen(Palette.TEXT_MUTED)
        painter.drawText(QRectF(x1 - 210, y1 - 36, 192, 20), Qt.AlignmentFlag.AlignRight, "MK I  //  HUD")
        painter.end()


class StarkHudFrame(QWidget):
    """Contenedor de video con cromado HUD."""

    def __init__(self, video_label, parent=None):
        super().__init__(parent)
        self.video_label = video_label
        self._color = Palette.HUD_CYAN
        stack_host = QWidget(self)
        stack = QStackedLayout(stack_host)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.addWidget(video_label)
        self.chrome = ViewportChrome()
        stack.addWidget(self.chrome)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(stack_host)

    def set_color(self, color: QColor):
        self._color = color
        self.chrome.set_color(color)


class GlassPanel(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 18, 18)
        painter.setBrush(Palette.GLASS)
        painter.setPen(QPen(QColor(80, 170, 210, 70), 1.2))
        painter.drawPath(path)
        highlight = QLinearGradient(0, 0, 0, self.height())
        highlight.setColorAt(0.0, QColor(255, 255, 255, 18))
        highlight.setColorAt(0.18, QColor(255, 255, 255, 0))
        painter.setBrush(highlight)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
        painter.end()


class ViernesDashboard(QMainWindow):
    """
    Dashboard de Viernes: sala de control cinematográfica.
    Conserva set_state / update_subtitle / update_frame para el orquestador.
    Incluye chat de texto y toggle de micrófono en el panel inferior.
    """

    def __init__(self, camera_stream, on_text_submitted=None):
        super().__init__()
        self.camera_stream = camera_stream
        self._on_text_submitted = on_text_submitted
        self._mic_enabled = True
        self.setWindowTitle("V.I.E.R.N.E.S.  ·  Control Room")
        self.setStyleSheet("background: transparent;")

        self.central_widget = Atmosphere(self)
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(36, 24, 36, 24)
        self.layout.setSpacing(16)

        self.top_bar = QHBoxLayout()
        self.top_bar.setSpacing(16)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(2)
        self.sys_label = QLabel("V.I.E.R.N.E.S.")
        self.sys_label.setFont(_mono(22, QFont.Weight.Bold))
        self.sys_label.setStyleSheet(f"color: {Palette.HUD_CYAN.name()}; background: transparent;")
        self.sys_meta = QLabel("SYSTEM MK I  ·  KIPPU CONTROL ROOM")
        self.sys_meta.setFont(_mono(11))
        self.sys_meta.setStyleSheet(f"color: {Palette.GOLD.name()}; background: transparent;")
        brand_box.addWidget(self.sys_label)
        brand_box.addWidget(self.sys_meta)
        self.top_bar.addLayout(brand_box)
        self.top_bar.addStretch()

        self.clock_label = QLabel()
        self.clock_label.setFont(_mono(18, QFont.Weight.Bold))
        self.clock_label.setStyleSheet(f"color: {Palette.TEXT_MAIN.name()}; background: transparent;")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.top_bar.addWidget(self.clock_label)

        self.status_label = QLabel("STANDBY")
        self.status_label.setFont(_mono(13, QFont.Weight.Bold))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setMinimumWidth(168)
        self.status_label.setFixedHeight(38)
        self._apply_status_style(Palette.HUD_CYAN)
        self.top_bar.addWidget(self.status_label)

        self.layout.addLayout(self.top_bar)

        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_label.setStyleSheet("background-color: rgba(2, 6, 12, 180); border-radius: 8px; color: #4aa8c8;")
        self.hud_frame = StarkHudFrame(self.video_label)
        self.layout.addWidget(self.hud_frame, stretch=1)

        self.bottom_host = GlassPanel()
        self.bottom_host.setFixedHeight(196)
        bottom = QVBoxLayout(self.bottom_host)
        bottom.setContentsMargins(22, 12, 28, 12)
        bottom.setSpacing(10)

        # --- Fila superior: indicador + subtítulo + barras ---
        top_row = QHBoxLayout()
        top_row.setSpacing(18)

        self.core_indicator = ArcReactorIndicator()
        top_row.addWidget(self.core_indicator, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        header_row = QHBoxLayout()
        self.speaker_label = QLabel("AWAITING INPUT")
        self.speaker_label.setFont(_mono(12, QFont.Weight.Bold))
        self.speaker_label.setStyleSheet(f"color: {Palette.HUD_CYAN.name()}; background: transparent;")
        header_row.addWidget(self.speaker_label)
        header_row.addStretch()
        self.bars = SignalBars()
        header_row.addWidget(self.bars)
        text_col.addLayout(header_row)

        self.subtitle_text = QLabel("Sistemas en línea. Te escucho.")
        self.subtitle_text.setWordWrap(True)
        self.subtitle_text.setFont(_sans(22, QFont.Weight.Medium))
        self.subtitle_text.setStyleSheet(f"color: {Palette.TEXT_MAIN.name()}; background: transparent;")
        text_col.addWidget(self.subtitle_text)
        top_row.addLayout(text_col, stretch=1)
        bottom.addLayout(top_row)

        # --- Fila inferior: chat de texto + toggle micrófono ---
        chat_row = QHBoxLayout()
        chat_row.setSpacing(10)

        self.mic_btn = QPushButton("🎙  MIC ON")
        self.mic_btn.setFont(_mono(11, QFont.Weight.Bold))
        self.mic_btn.setFixedSize(110, 36)
        self.mic_btn.setCheckable(True)
        self.mic_btn.setChecked(True)
        self.mic_btn.clicked.connect(self._toggle_mic)
        self._update_mic_style(True)
        chat_row.addWidget(self.mic_btn)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Escribí tu pregunta y presioná Enter...")
        self.chat_input.setFont(_sans(16))
        self.chat_input.setFixedHeight(36)
        self.chat_input.setStyleSheet(
            f"""
            QLineEdit {{
                background: rgba(8, 20, 38, 200);
                color: {Palette.TEXT_MAIN.name()};
                border: 1px solid rgba(64, 224, 255, 90);
                border-radius: 6px;
                padding: 0 12px;
                selection-background-color: rgba(64, 224, 255, 60);
            }}
            QLineEdit:focus {{
                border: 1px solid {Palette.HUD_CYAN.name()};
                background: rgba(10, 26, 50, 220);
            }}
            """
        )
        self.chat_input.returnPressed.connect(self._submit_chat)
        chat_row.addWidget(self.chat_input, stretch=1)

        self.send_btn = QPushButton("ENVIAR  ▶")
        self.send_btn.setFont(_mono(11, QFont.Weight.Bold))
        self.send_btn.setFixedSize(110, 36)
        self.send_btn.clicked.connect(self._submit_chat)
        self.send_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: rgba(64, 224, 255, 22);
                color: {Palette.HUD_CYAN.name()};
                border: 1px solid rgba(64, 224, 255, 120);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: rgba(64, 224, 255, 45);
                border: 1px solid {Palette.HUD_CYAN.name()};
            }}
            QPushButton:pressed {{ background: rgba(64, 224, 255, 70); }}
            """
        )
        chat_row.addWidget(self.send_btn)

        bottom.addLayout(chat_row)
        self.layout.addWidget(self.bottom_host)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)
        self._tick_clock()
        self.set_state(ViernesState.IDLE)

    def _apply_status_style(self, color: QColor):
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                color: {color.name()};
                background: rgba({color.red()}, {color.green()}, {color.blue()}, 28);
                border: 1px solid rgba({color.red()}, {color.green()}, {color.blue()}, 140);
                border-radius: 19px;
                padding: 0 16px;
            }}
            """
        )

    def _update_mic_style(self, enabled: bool) -> None:
        if enabled:
            self.mic_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: rgba(72, 255, 186, 28);
                    color: {Palette.HUD_GREEN.name()};
                    border: 1px solid rgba(72, 255, 186, 140);
                    border-radius: 6px;
                }}
                QPushButton:hover {{ background: rgba(72, 255, 186, 55); }}
                """
            )
        else:
            self.mic_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: rgba(255, 86, 110, 22);
                    color: {Palette.HUD_RED.name()};
                    border: 1px solid rgba(255, 86, 110, 120);
                    border-radius: 6px;
                }}
                QPushButton:hover {{ background: rgba(255, 86, 110, 45); }}
                """
            )

    def _toggle_mic(self, checked: bool) -> None:
        self._mic_enabled = checked
        self.mic_btn.setText("🎙  MIC ON" if checked else "🚫  MIC OFF")
        self._update_mic_style(checked)
        # Notificar al orquestador si registró un callback
        if hasattr(self, "_on_mic_toggled") and self._on_mic_toggled:
            self._on_mic_toggled(checked)

    def set_mic_callback(self, callback) -> None:
        """Registra el callback para toggle de micrófono (lo llama el orquestador)."""
        self._on_mic_toggled = callback

    def _submit_chat(self) -> None:
        """Envía el texto del chat al orquestador."""
        text = self.chat_input.text().strip()
        if not text:
            return
        self.chat_input.clear()
        logger.info(f"[CHAT] Texto enviado: '{text}'")
        self.update_subtitle(f"Usuario: {text}")
        if self._on_text_submitted:
            self._on_text_submitted(text)

    def _tick_clock(self):
        now = _dt.datetime.now()
        self.clock_label.setText(now.strftime("%H:%M:%S    %d · %b · %Y").upper())

    def set_state(self, state: str):
        self.core_indicator.set_state(state)
        self.bars.set_state(state)
        color = _state_color(state)
        labels = {
            ViernesState.THINKING: "PROCESSING",
            ViernesState.SPEAKING: "TRANSMITTING",
            ViernesState.LISTENING: "LISTENING",
            ViernesState.ERROR: "FAULT",
        }
        self.hud_frame.set_color(color)
        self.status_label.setText(labels.get(state, "STANDBY"))
        self._apply_status_style(color)

    def update_subtitle(self, text: str):
        if text.startswith("Usuario:"):
            display_text = text[len("Usuario:"):].strip()
            self.speaker_label.setText("AUDIO INPUT DETECTED")
            self.speaker_label.setStyleSheet(f"color: {Palette.HUD_AMBER.name()}; background: transparent;")
            self.set_state(ViernesState.THINKING)
        elif text.startswith("Viernes:"):
            display_text = text[len("Viernes:"):].strip()
            self.speaker_label.setText("AUDIO OUTPUT")
            self.speaker_label.setStyleSheet(f"color: {Palette.HUD_GREEN.name()}; background: transparent;")
            self.set_state(ViernesState.SPEAKING)
            QTimer.singleShot(4000, lambda: self.set_state(ViernesState.LISTENING))
        else:
            display_text = text
            self.speaker_label.setText("CHANNEL OPEN")
            self.speaker_label.setStyleSheet(f"color: {Palette.HUD_CYAN.name()}; background: transparent;")
            self.set_state(ViernesState.LISTENING)

        self.subtitle_text.setText(display_text)

    def update_frame(self):
        get_rgb = getattr(self.camera_stream, "get_latest_frame_rgb", None)
        frame_rgb = get_rgb() if get_rgb else None

        if frame_rgb is None and self.camera_stream is not None:
            frame_bgr = self.camera_stream.get_latest_frame()
            if frame_bgr is not None:
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        if frame_rgb is not None:
            h, w, ch = frame_rgb.shape
            # .copy() es necesario porque camera_stream retorna referencia directa
            # y el hilo de captura puede reciclar el buffer antes de que Qt renderice
            frame_rgb = frame_rgb.copy()
            bytes_per_line = ch * w
            q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img).scaled(
                max(1, self.video_label.width()),
                max(1, self.video_label.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self.video_label.setPixmap(pixmap)
            self.video_label.setText("")
        else:
            self.video_label.setPixmap(QPixmap())
            self.video_label.setFont(_mono(18))
            self.video_label.setText("NO VIDEO FEED")
            self.video_label.setStyleSheet(
                f"background-color: rgba(2, 6, 12, 180); color: {Palette.TEXT_MUTED.name()};"
            )

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
        elif event.key() == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        logger.info("Cerrando ViernesDashboard...")
        if self.camera_stream:
            self.camera_stream.stop()
        self.timer.stop()
        self.clock_timer.stop()
        event.accept()


if __name__ == "__main__":
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from viernes.ipcam.camera_stream import IPCameraStream

    app = QApplication(sys.argv)
    stream = IPCameraStream("0")
    dashboard = ViernesDashboard(stream)
    dashboard.showMaximized()
    sys.exit(app.exec())
