import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from src.content.config import GAME_ICON, ICONS_DIR


class MessageDialog(QDialog):
    """Reusable app-styled dialog wrapper for all info/warning/event popups.

    Provides a consistent layout: icon (optional), title, body text,
    and a configurable button box. All dialog types share this base
    styling and window behavior.
    """

    def __init__(self, title, body, parent=None, icon_path=None, buttons=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(400, 200)
        self.setWindowIcon(QIcon(GAME_ICON))
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)

        header = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setMinimumSize(64, 64)
        self.icon_label.setMaximumSize(64, 64)
        self.icon_label.setAlignment(Qt.AlignCenter)
        header.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        header.addWidget(self.title_label, 1)
        main_layout.addLayout(header)

        self.body_text = QTextEdit()
        self.body_text.setReadOnly(True)
        self.body_text.setPlainText(body)
        self.body_text.setStyleSheet("font-size: 12px;")
        main_layout.addWidget(self.body_text, 1)

        if buttons is None:
            buttons = QDialogButtonBox.StandardButton.Ok
        self.button_box = QDialogButtonBox(buttons)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        if icon_path:
            self.set_icon(icon_path)

    def set_icon(self, icon_path):
        if not icon_path:
            return
        try:
            pix = QPixmap(icon_path)
            if not pix.isNull():
                scaled = pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.icon_label.setPixmap(scaled)
        except Exception:
            pass

    def set_body(self, text):
        self.body_text.setPlainText(text)

    def set_body_html(self, html):
        self.body_text.setHtml(html)


def show_info_dialog(title, body, parent=None):
    dialog = MessageDialog(title, body, parent=parent)
    icon_path = os.path.join(ICONS_DIR, "info.svg")
    if os.path.exists(icon_path):
        dialog.set_icon(icon_path)
    dialog.exec()


def show_warning_dialog(title, body, parent=None, icon_path=None):
    dialog = MessageDialog(title, body, parent=parent)
    if icon_path is None:
        icon_path = os.path.join(ICONS_DIR, "warning.svg")
    if icon_path and os.path.exists(icon_path):
        dialog.set_icon(icon_path)
    dialog.exec()


def show_event_dialog(title, body, parent=None, icon_path=None):
    if icon_path is None:
        icon_path = os.path.join(ICONS_DIR, "event.svg")
    dialog = MessageDialog(title, body, parent=parent, icon_path=icon_path)
    dialog.exec()


def show_question_dialog(title, body, parent=None):
    dialog = MessageDialog(title, body, parent=parent, buttons=QDialogButtonBox.Yes | QDialogButtonBox.No)
    result = dialog.exec()
    return result == QDialog.Accepted
