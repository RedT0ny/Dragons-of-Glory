# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'notes_dialog.ui'
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
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QPlainTextEdit,
    QPushButton, QSizePolicy, QSpacerItem, QVBoxLayout,
    QWidget)

class Ui_notesDialog(object):
    def setupUi(self, notesDialog):
        if not notesDialog.objectName():
            notesDialog.setObjectName(u"notesDialog")
        notesDialog.setWindowModality(Qt.WindowModality.WindowModal)
        notesDialog.resize(400, 300)
        self.verticalLayoutWidget = QWidget(notesDialog)
        self.verticalLayoutWidget.setObjectName(u"verticalLayoutWidget")
        self.verticalLayoutWidget.setGeometry(QRect(30, 20, 341, 251))
        self.verticalLayout = QVBoxLayout(self.verticalLayoutWidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.notesTextEdit = QPlainTextEdit(self.verticalLayoutWidget)
        self.notesTextEdit.setObjectName(u"notesTextEdit")

        self.verticalLayout.addWidget(self.notesTextEdit)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalSpacer = QSpacerItem(78, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.notesOkButton = QPushButton(self.verticalLayoutWidget)
        self.notesOkButton.setObjectName(u"notesOkButton")

        self.horizontalLayout.addWidget(self.notesOkButton)

        self.horizontalSpacer_2 = QSpacerItem(88, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer_2)


        self.verticalLayout.addLayout(self.horizontalLayout)


        self.retranslateUi(notesDialog)
        self.notesOkButton.clicked.connect(notesDialog.close)

        QMetaObject.connectSlotsByName(notesDialog)
    # setupUi

    def retranslateUi(self, notesDialog):
        notesDialog.setWindowTitle(QCoreApplication.translate("notesDialog", u"Scenario notes", None))
        self.notesOkButton.setText(QCoreApplication.translate("notesDialog", u"Ok", None))
    # retranslateUi


class NotesDialog(QDialog):
    """
    Dialog to display scenario notes.
    """
    def __init__(self, notes_text, parent=None):
        super().__init__(parent)
        self.ui = Ui_notesDialog()
        self.ui.setupUi(self)

        # Set the notes text
        self.ui.notesTextEdit.setPlainText(notes_text)
        self.ui.notesTextEdit.setReadOnly(True)

