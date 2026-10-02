"""Dashboard HUD estilo J.A.R.V.I.S. / F.R.I.D.A.Y. para monitor secundario (TV)."""

import sys
import math
import logging
import cv2
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QImage, QPixmap, QFont, QPainter, QColor, QPen, QBrush, QPainterPath,
    QLinearGradient
)

logger = logging.getLogger(__name__)

class Palette:
    BG_BASE       = QColor(2, 4, 8)
    HUD_CYAN      = QColor(0, 230, 255)
    HUD_CYAN_GLOW = QColor(0, 230, 255, 60)
    HUD_AMBER     = QColor(255, 170, 0)
    HUD_GREEN     = QColor(0, 255, 150)
    HUD_DIM       = QColor(0, 230, 255, 40)
    TEXT_MAIN     = QColor(220, 240, 255)

class ViernesState:
    IDLE      = "idle"
    LISTENING = "listening"
    THINKING  = "thinking"
    SPEAKING  = "speaking"
    ERROR     = "error"


class ArcReactorIndicator(QWidget):
    """Anillo concéntrico que gira y pulsa, estilo IA de Tony Stark."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 100)
        self._rotation = 0.0
        self._pulse = 0.0
        self._color = Palette.HUD_CYAN
        self._speed = 2.0
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(33)
        
    def set_state(self, state: str):
        if state == ViernesState.LISTENING:
            self._color = Palette.HUD_CYAN
            self._speed = 4.0
        elif state == ViernesState.THINKING:
            self._color = Palette.HUD_AMBER
            self._speed = 12.0
        elif state == ViernesState.SPEAKING:
            self._color = Palette.HUD_GREEN
            self._speed = 6.0
        else:
            self._color = Palette.HUD_DIM
            self._speed = 1.0

    def _animate(self):
        self._rotation = (self._rotation + self._speed) % 360
        self._pulse += 0.1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        cx, cy = self.width() / 2, self.height() / 2
        
        # Glow base
        pulse_alpha = int(40 + 20 * math.sin(self._pulse))
        glow_color = QColor(self._color)
        glow_color.setAlpha(pulse_alpha)
        painter.setBrush(QBrush(glow_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 35, 35)
        
        # Anillos
        painter.translate(cx, cy)
        painter.rotate(self._rotation)
        
        # Anillo externo punteado
        pen = QPen(self._color, 2)
        pen.setDashPattern([4, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 42, 42)
        
        # Anillo interno con cortes
        painter.rotate(-self._rotation * 1.5) # Rota en dirección contraria
        pen.setDashPattern([15, 5, 2, 5])
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(0, 0), 28, 28)
        
        # Núcleo
        painter.setPen(Qt.PenStyle.NoPen)
        core_color = QColor(self._color)
        core_color.setAlpha(180)
        painter.setBrush(core_color)
        painter.drawEllipse(QPointF(0, 0), 10, 10)
        
        painter.end()


class StarkHudFrame(QWidget):
    """Contenedor de video con bordes chamfered (angulados) tipo HUD militar/sci-fi."""
    def __init__(self, video_label, parent=None):
        super().__init__(parent)
        self.video_label = video_label
        self._color = Palette.HUD_CYAN
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(video_label)
        
    def set_color(self, color: QColor):
        self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w, h = self.width(), self.height()
        c = 30 # Tamaño del corte (chamfer)
        
        # Path del borde angulado
        path = QPainterPath()
        path.moveTo(c, 0)
        path.lineTo(w - c, 0)
        path.lineTo(w, c)
        path.lineTo(w, h - c)
        path.lineTo(w - c, h)
        path.lineTo(c, h)
        path.lineTo(0, h - c)
        path.lineTo(0, c)
        path.closeSubpath()
        
        # Fondo sutil
        fill_color = QColor(self._color)
        fill_color.setAlpha(10)
        painter.setBrush(QBrush(fill_color))
        
        # Borde brillante
        pen = QPen(self._color, 2)
        painter.setPen(pen)
        painter.drawPath(path)
        
        # Detalles de las esquinas (Cruces de enfoque)
        L = 20
        pen.setWidth(3)
        painter.setPen(pen)
        # Top Left
        painter.drawLine(0, c, L, c)
        painter.drawLine(c, 0, c, L)
        # Bottom Right
        painter.drawLine(w, h - c, w - L, h - c)
        painter.drawLine(w - c, h, w - c, h - L)
        
        painter.end()


class ViernesDashboard(QMainWindow):
    """
    Dashboard de Viernes, rediseñado con estética técnica HUD (J.A.R.V.I.S).
    Fondo super oscuro, colores de alto contraste, elementos geométricos.
    """
    def __init__(self, camera_stream):
        super().__init__()
        self.camera_stream = camera_stream
        
        self.setWindowTitle("V.I.E.R.N.E.S. HUD")
        self.setStyleSheet(f"background-color: {Palette.BG_BASE.name()};")

        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)
        
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(40, 30, 40, 30)
        self.layout.setSpacing(20)
        
        # --- Top Bar (Telemetría) ---
        self.top_bar = QHBoxLayout()
        
        # Título técnico
        self.sys_label = QLabel("SYSTEM: V.I.E.R.N.E.S. // MK I")
        self.sys_label.setStyleSheet(f"color: {Palette.HUD_CYAN.name()}; font-family: monospace; font-size: 16px; font-weight: bold; letter-spacing: 2px;")
        self.top_bar.addWidget(self.sys_label)
        
        self.top_bar.addStretch()
        
        # Status Label
        self.status_label = QLabel("[ ONLINE ]")
        self.status_label.setStyleSheet(f"color: {Palette.HUD_CYAN.name()}; font-family: monospace; font-size: 16px; font-weight: bold; letter-spacing: 2px;")
        self.top_bar.addWidget(self.status_label)
        
        self.layout.addLayout(self.top_bar)
        
        # --- Center: Video con marco HUD ---
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_label.setStyleSheet("background-color: transparent;")
        
        self.hud_frame = StarkHudFrame(self.video_label)
        self.layout.addWidget(self.hud_frame, stretch=1)
        
        # --- Bottom Panel (Core + Subtítulos) ---
        self.bottom_panel = QHBoxLayout()
        self.bottom_panel.setContentsMargins(20, 10, 20, 10)
        
        # Indicador Rotativo (El "Arc Reactor")
        self.core_indicator = ArcReactorIndicator()
        self.bottom_panel.addWidget(self.core_indicator)
        
        # Contenedor de Texto
        self.text_layout = QVBoxLayout()
        self.text_layout.setContentsMargins(20, 0, 0, 0)
        
        self.speaker_label = QLabel("AWAITING INPUT...")
        self.speaker_label.setStyleSheet(f"color: {Palette.HUD_CYAN.name()}; font-family: monospace; font-size: 12px; letter-spacing: 3px;")
        self.text_layout.addWidget(self.speaker_label)
        
        self.subtitle_text = QLabel("Sistemas en línea. Te escucho.")
        self.subtitle_text.setWordWrap(True)
        # Tipografía sans-serif limpia para el subtítulo real para facilitar lectura
        self.subtitle_text.setStyleSheet(f"color: {Palette.TEXT_MAIN.name()}; font-size: 26px; font-weight: 500;")
        self.text_layout.addWidget(self.subtitle_text)
        
        self.text_layout.addStretch()
        self.bottom_panel.addLayout(self.text_layout)
        
        self.layout.addLayout(self.bottom_panel)
        
        # --- Timer ---
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)

    def set_state(self, state: str):
        self.core_indicator.set_state(state)
        
        if state == ViernesState.THINKING:
            color = Palette.HUD_AMBER
            status_txt = "[ PROCESSING ]"
        elif state == ViernesState.SPEAKING:
            color = Palette.HUD_GREEN
            status_txt = "[ TRANSMITTING ]"
        elif state == ViernesState.LISTENING:
            color = Palette.HUD_CYAN
            status_txt = "[ LISTENING ]"
        else:
            color = Palette.HUD_DIM
            status_txt = "[ STANDBY ]"
            
        self.hud_frame.set_color(color)
        self.status_label.setText(status_txt)
        self.status_label.setStyleSheet(f"color: {color.name()}; font-family: monospace; font-size: 16px; font-weight: bold; letter-spacing: 2px;")
        
    def update_subtitle(self, text: str):
        if text.startswith("Usuario:"):
            display_text = text[len("Usuario:"):].strip()
            self.speaker_label.setText("AUDIO INPUT DETECTED")
            self.speaker_label.setStyleSheet(f"color: {Palette.HUD_AMBER.name()}; font-family: monospace; font-size: 12px; letter-spacing: 3px;")
            self.set_state(ViernesState.THINKING)
        elif text.startswith("Viernes:"):
            display_text = text[len("Viernes:"):].strip()
            self.speaker_label.setText("AUDIO OUTPUT")
            self.speaker_label.setStyleSheet(f"color: {Palette.HUD_GREEN.name()}; font-family: monospace; font-size: 12px; letter-spacing: 3px;")
            self.set_state(ViernesState.SPEAKING)
            QTimer.singleShot(4000, lambda: self.set_state(ViernesState.LISTENING))
        else:
            display_text = text
            self.set_state(ViernesState.LISTENING)

        self.subtitle_text.setText(f'"{display_text}"' if display_text else "")

    def update_frame(self):
        frame = self.camera_stream.get_latest_frame()
        if frame is not None:
            # Efecto opcional: Convertir frame a escala de grises/cyanizado
            # Para un HUD real, dejaremos el RGB pero podrías mezclar el color base.
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w

            q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img).scaled(
                self.video_label.width(), 
                self.video_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.video_label.setPixmap(pixmap)
        else:
            self.video_label.setText("[ NO VIDEO FEED ]")
            self.video_label.setStyleSheet(f"color: {Palette.HUD_DIM.name()}; font-family: monospace; font-size: 20px;")

    def closeEvent(self, event):
        logger.info("Cerrando ViernesDashboard...")
        if self.camera_stream:
            self.camera_stream.stop()
        self.timer.stop()
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
