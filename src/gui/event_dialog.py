# -*- coding: utf-8 -*-
import os

################################################################################
## Form generated from reading UI file 'event_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QDialogButtonBox,
    QGridLayout, QLabel, QSizePolicy, QTextEdit,
    QWidget)

from src.content.config import IMAGES_DIR
from src.content.translator import Translator


class Ui_event_dialog(object):
    def setupUi(self, event_dialog):
        if not event_dialog.objectName():
            event_dialog.setObjectName(u"event_dialog")
        event_dialog.resize(1024, 576)
        self.gridLayoutWidget = QWidget(event_dialog)
        self.gridLayoutWidget.setObjectName(u"gridLayoutWidget")
        self.gridLayoutWidget.setGeometry(QRect(0, 10, 1021, 561))
        self.event_layout = QGridLayout(self.gridLayoutWidget)
        self.event_layout.setObjectName(u"event_layout")
        self.event_layout.setContentsMargins(0, 0, 0, 0)
        self.event_description = QTextEdit(self.gridLayoutWidget)
        self.event_description.setObjectName(u"event_description")
        font = QFont()
        font.setPointSize(16)
        self.event_description.setFont(font)
        self.event_description.setReadOnly(True)

        self.event_layout.addWidget(self.event_description, 4, 0, 1, 3)

        self.event_buttons = QDialogButtonBox(self.gridLayoutWidget)
        self.event_buttons.setObjectName(u"event_buttons")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.event_buttons.sizePolicy().hasHeightForWidth())
        self.event_buttons.setSizePolicy(sizePolicy)
        self.event_buttons.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.event_buttons.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.event_buttons.setOrientation(Qt.Orientation.Horizontal)
        self.event_buttons.setStandardButtons(QDialogButtonBox.StandardButton.Ok)

        self.event_layout.addWidget(self.event_buttons, 5, 1, 1, 1, Qt.AlignmentFlag.AlignHCenter)

        self.event_picture = QLabel(self.gridLayoutWidget)
        self.event_picture.setObjectName(u"event_picture")
        sizePolicy.setHeightForWidth(self.event_picture.sizePolicy().hasHeightForWidth())
        self.event_picture.setSizePolicy(sizePolicy)
        self.event_picture.setMinimumSize(QSize(592, 333))
        self.event_picture.setMaximumSize(QSize(768, 432))
        self.event_picture.setAutoFillBackground(False)
        self.event_picture.setStyleSheet(u"background-color: #333; color: white;")
        self.event_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.event_layout.addWidget(self.event_picture, 2, 1, 1, 1)

        self.event_title = QLabel(self.gridLayoutWidget)
        self.event_title.setObjectName(u"event_title")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.event_title.sizePolicy().hasHeightForWidth())
        self.event_title.setSizePolicy(sizePolicy1)
        self.event_title.setMaximumSize(QSize(16777215, 35))
        font1 = QFont()
        font1.setFamilies([u"Libra"])
        font1.setPointSize(36)
        self.event_title.setFont(font1)
        self.event_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.event_layout.addWidget(self.event_title, 3, 1, 1, 1)


        self.retranslateUi(event_dialog)
        self.event_buttons.rejected.connect(event_dialog.reject)
        self.event_buttons.accepted.connect(event_dialog.accept)

        QMetaObject.connectSlotsByName(event_dialog)
    # setupUi

    def retranslateUi(self, event_dialog):
        event_dialog.setWindowTitle(QCoreApplication.translate("event_dialog", u"Event", None))
        self.event_description.setDocumentTitle("")
        self.event_description.setPlaceholderText(QCoreApplication.translate("event_dialog", u"event_description", None))
        self.event_picture.setText(QCoreApplication.translate("event_dialog", u"event_picture", None))
        self.event_title.setText(QCoreApplication.translate("event_dialog", u"Event Title", None))
    # retranslateUi

class EventDialog(QDialog, Ui_event_dialog):
    def __init__(self, event, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.event = event
        self.translator = Translator()
        self._apply_translations()
        self.populate()

    def _apply_translations(self):
        tr = self.translator.tr
        self.setWindowTitle(tr("dialogs.event.window_title", "Event"))
        self.event_description.setPlaceholderText(tr("dialogs.event.description_placeholder", "Event description"))
        self.event_picture.setText(tr("dialogs.event.picture_placeholder", "Event image"))
        self.event_title.setText(tr("dialogs.event.title_placeholder", "Event Title"))

        ok_btn = self.event_buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText(tr("dialogs.common.ok", "OK"))

    def populate(self):
        if not self.event:
            return

        # Title
        title = self.event.spec.id.replace("_", " ").title()
        self.setWindowTitle(
            self.translator.tr(
                "dialogs.event.strategic_title",
                "Strategic Event: {title}",
                title=title,
            )
        )
        self.event_title.setText(title)

        # Description
        self.event_description.setText(self.event.description)

        # Picture
        if self.event.spec.picture:
            image_path = os.path.join(IMAGES_DIR, self.event.spec.picture)
            if os.path.exists(image_path):
                pix = QPixmap(image_path)
                # Keep aspect ratio
                self.event_picture.setPixmap(pix.scaled(self.event_picture.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.event_picture.setText("")
