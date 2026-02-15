# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'turn_panel.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
    QSizePolicy, QVBoxLayout, QWidget)

from src.content.config import BASE_DIR, LOGO_HL, LOGO_WS
from src.content.constants import HL, WS

import os

class Ui_turn_panel(object):
    def setupUi(self, turn_panel):
        if not turn_panel.objectName():
            turn_panel.setObjectName(u"turn_panel")
        turn_panel.resize(350, 120)
        turn_panel.setFrameShape(QFrame.Shape.StyledPanel)
        turn_panel.setFrameShadow(QFrame.Shadow.Sunken)
        self.horizontalLayout = QHBoxLayout(turn_panel)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.sideLbl = QLabel(turn_panel)
        self.sideLbl.setObjectName(u"sideLbl")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.sideLbl.sizePolicy().hasHeightForWidth())
        self.sideLbl.setSizePolicy(sizePolicy)
        self.sideLbl.setMaximumSize(QSize(175, 100))
        font = QFont()
        font.setFamilies([u"Libra"])
        font.setPointSize(24)
        self.sideLbl.setFont(font)
        self.sideLbl.setPixmap(QPixmap(LOGO_WS))
        self.sideLbl.setScaledContents(True)
        self.sideLbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout.addWidget(self.sideLbl)

        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.calendarLbl = QLabel(turn_panel)
        self.calendarLbl.setObjectName(u"calendarLbl")
        font1 = QFont()
        font1.setFamilies([u"Libra"])
        font1.setPointSize(16)
        self.calendarLbl.setFont(font1)
        self.calendarLbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout.addWidget(self.calendarLbl)

        self.turnLbl = QLabel(turn_panel)
        self.turnLbl.setObjectName(u"turnLbl")
        self.turnLbl.setFont(font)
        self.turnLbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout.addWidget(self.turnLbl)

        self.phaseLbl = QLabel(turn_panel)
        self.phaseLbl.setObjectName(u"phaseLbl")
        self.phaseLbl.setFont(font1)
        self.phaseLbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout.addWidget(self.phaseLbl)


        self.horizontalLayout.addLayout(self.verticalLayout)


        self.retranslateUi(turn_panel)

        QMetaObject.connectSlotsByName(turn_panel)
    # setupUi

    def retranslateUi(self, turn_panel):
        self.sideLbl.setText("")
        self.calendarLbl.setText(QCoreApplication.translate("turn_panel", u"Mar/Apr 348", None))
        self.turnLbl.setText(QCoreApplication.translate("turn_panel", u"30", None))
        self.phaseLbl.setText(QCoreApplication.translate("turn_panel", u"Movement", None))
        pass
    # retranslateUi


class TurnPanel(QFrame):
    """View widget for turn-tracking labels and side logo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ui = Ui_turn_panel()
        self._ui.setupUi(self)
        self.setFixedWidth(self.width())
        self.setFixedHeight(100)
        self.sideLbl = self._ui.sideLbl
        self.turnLbl = self._ui.turnLbl
        self.calendarLbl = self._ui.calendarLbl
        self.phaseLbl = self._ui.phaseLbl

    def update_state(self, active_player: str, turn: int, calendar_upper_label: str, phase_label: str):
        logo_path = LOGO_HL if active_player == HL else LOGO_WS if active_player == WS else ""
        if self.sideLbl is not None:
            if logo_path and os.path.exists(logo_path):
                self.sideLbl.setPixmap(QPixmap(logo_path))
            else:
                self.sideLbl.clear()
        if self.turnLbl is not None:
            self.turnLbl.setText(str(turn))
        if self.calendarLbl is not None:
            self.calendarLbl.setText(calendar_upper_label or "")
        if self.phaseLbl is not None:
            self.phaseLbl.setText(phase_label or "")
