# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'side_selection_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QFormLayout, QLabel, QSizePolicy,
    QVBoxLayout, QWidget)

class Ui_sideSelectDialog(object):
    def setupUi(self, sideSelectDialog):
        if not sideSelectDialog.objectName():
            sideSelectDialog.setObjectName(u"sideSelectDialog")
        sideSelectDialog.resize(238, 115)
        self.widget = QWidget(sideSelectDialog)
        self.widget.setObjectName(u"widget")
        self.widget.setGeometry(QRect(40, 10, 158, 91))
        self.verticalLayout = QVBoxLayout(self.widget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.formLayout = QFormLayout()
        self.formLayout.setObjectName(u"formLayout")
        self.wsControlLabel = QLabel(self.widget)
        self.wsControlLabel.setObjectName(u"wsControlLabel")
        font = QFont()
        font.setBold(True)
        self.wsControlLabel.setFont(font)

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.wsControlLabel)

        self.hlControlLabel = QLabel(self.widget)
        self.hlControlLabel.setObjectName(u"hlControlLabel")
        self.hlControlLabel.setFont(font)

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.hlControlLabel)

        self.hlComboBox = QComboBox(self.widget)
        self.hlComboBox.addItem("")
        self.hlComboBox.addItem("")
        self.hlComboBox.setObjectName(u"hlComboBox")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.hlComboBox)

        self.wsComboBox = QComboBox(self.widget)
        self.wsComboBox.addItem("")
        self.wsComboBox.addItem("")
        self.wsComboBox.setObjectName(u"wsComboBox")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.wsComboBox)


        self.verticalLayout.addLayout(self.formLayout)

        self.buttonBox = QDialogButtonBox(self.widget)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)

        self.verticalLayout.addWidget(self.buttonBox)


        self.retranslateUi(sideSelectDialog)
        self.buttonBox.accepted.connect(sideSelectDialog.accept)
        self.buttonBox.rejected.connect(sideSelectDialog.reject)

        QMetaObject.connectSlotsByName(sideSelectDialog)
    # setupUi

    def retranslateUi(self, sideSelectDialog):
        sideSelectDialog.setWindowTitle(QCoreApplication.translate("sideSelectDialog", u"Select sides", None))
        self.wsControlLabel.setText(QCoreApplication.translate("sideSelectDialog", u"Whitestone", None))
        self.hlControlLabel.setText(QCoreApplication.translate("sideSelectDialog", u"Highlord", None))
        self.hlComboBox.setItemText(0, QCoreApplication.translate("sideSelectDialog", u"Human", None))
        self.hlComboBox.setItemText(1, QCoreApplication.translate("sideSelectDialog", u"AI", None))

        self.wsComboBox.setItemText(0, QCoreApplication.translate("sideSelectDialog", u"Human", None))
        self.wsComboBox.setItemText(1, QCoreApplication.translate("sideSelectDialog", u"AI", None))

    # retranslateUi

class SideSelectionDialog(QDialog):
    """
    Dialog to choose which sides are controlled by Human or AI.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_sideSelectDialog()
        self.ui.setupUi(self)

    def get_player_config(self):
        """
        Returns a dictionary mapping side to AI status (True for AI, False for Human).
        """
        # Logic depends on your UI layout, assuming QComboBox or QRadioButton
        # Example assuming 'hlTypeCombo' and 'wsTypeCombo' exist in your UI
        hl_is_ai = self.ui.hlComboBox.currentText() == "AI"
        ws_is_ai = self.ui.wsComboBox.currentText() == "AI"

        return {
            "highlord_ai": hl_is_ai,
            "whitestone_ai": ws_is_ai
        }