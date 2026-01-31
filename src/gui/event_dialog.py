# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'event_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.9.1
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

class Ui_event_dialog(object):
    def setupUi(self, event_dialog):
        if not event_dialog.objectName():
            event_dialog.setObjectName(u"event_dialog")
        event_dialog.resize(640, 360)
        self.gridLayoutWidget = QWidget(event_dialog)
        self.gridLayoutWidget.setObjectName(u"gridLayoutWidget")
        self.gridLayoutWidget.setGeometry(QRect(10, 10, 621, 344))
        self.event_layout = QGridLayout(self.gridLayoutWidget)
        self.event_layout.setObjectName(u"event_layout")
        self.event_layout.setContentsMargins(0, 0, 0, 0)
        self.event_picture = QLabel(self.gridLayoutWidget)
        self.event_picture.setObjectName(u"event_picture")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.event_picture.sizePolicy().hasHeightForWidth())
        self.event_picture.setSizePolicy(sizePolicy)
        self.event_picture.setMinimumSize(QSize(192, 108))
        self.event_picture.setMaximumSize(QSize(240, 135))
        self.event_picture.setAutoFillBackground(False)
        self.event_picture.setStyleSheet(u"background-color: #333; color: white;")
        self.event_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.event_layout.addWidget(self.event_picture, 2, 1, 1, 1)

        self.event_description = QTextEdit(self.gridLayoutWidget)
        self.event_description.setObjectName(u"event_description")

        self.event_layout.addWidget(self.event_description, 3, 0, 1, 3)

        self.event_buttons = QDialogButtonBox(self.gridLayoutWidget)
        self.event_buttons.setObjectName(u"event_buttons")
        sizePolicy.setHeightForWidth(self.event_buttons.sizePolicy().hasHeightForWidth())
        self.event_buttons.setSizePolicy(sizePolicy)
        self.event_buttons.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.event_buttons.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.event_buttons.setOrientation(Qt.Orientation.Horizontal)
        self.event_buttons.setStandardButtons(QDialogButtonBox.StandardButton.Ok)

        self.event_layout.addWidget(self.event_buttons, 4, 1, 1, 1, Qt.AlignmentFlag.AlignHCenter)


        self.retranslateUi(event_dialog)
        self.event_buttons.rejected.connect(event_dialog.reject)
        self.event_buttons.accepted.connect(event_dialog.accept)

        QMetaObject.connectSlotsByName(event_dialog)
    # setupUi

    def retranslateUi(self, event_dialog):
        event_dialog.setWindowTitle(QCoreApplication.translate("event_dialog", u"Event", None))
        self.event_picture.setText(QCoreApplication.translate("event_dialog", u"event_picture", None))
        self.event_description.setDocumentTitle("")
        self.event_description.setPlaceholderText(QCoreApplication.translate("event_dialog", u"event_description", None))
    # retranslateUi

