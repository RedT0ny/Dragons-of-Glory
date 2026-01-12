# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'new_game_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.9.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
                            QMetaObject, QObject, QPoint, QRect,
                            QSize, QTime, QUrl, Qt, QDir)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QPushButton, QSizePolicy,
                               QSpacerItem, QTextEdit, QVBoxLayout, QWidget, QFileSystemModel)
from src.content.config import SCENARIOS_DIR


class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.setWindowModality(Qt.WindowModality.NonModal)
        Dialog.resize(1280, 720)
        Dialog.setWindowOpacity(0.7)
        Dialog.setModal(True)
        self.horizontalLayout = QHBoxLayout(Dialog)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.scGroupBox = QGroupBox(Dialog)
        self.scGroupBox.setObjectName(u"scGroupBox")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.scGroupBox.sizePolicy().hasHeightForWidth())
        self.scGroupBox.setSizePolicy(sizePolicy)
        self.scGroupBox.setMinimumSize(QSize(400, 0))
        self.scGroupBox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.formLayout = QFormLayout(self.scGroupBox)
        self.formLayout.setObjectName(u"formLayout")
        self.scListView = QListView(self.scGroupBox)
        self.scListView.setObjectName(u"scListView")

        # Set up the file system model to list scenario files
        file_list_model = QFileSystemModel(self.scListView)
        file_list_model.setRootPath(SCENARIOS_DIR)
        file_list_model.setNameFilters([u"*.yaml"])
        file_list_model.setNameFilterDisables(False)  # Hide non-matching files
        self.scListView.setModel(file_list_model)
        self.scListView.setRootIndex(file_list_model.index(SCENARIOS_DIR))

        self.formLayout.setWidget(0, QFormLayout.ItemRole.SpanningRole, self.scListView)

        self.horizontalLayout.addWidget(self.scGroupBox)

        self.detailsGroupBox = QGroupBox(Dialog)
        self.detailsGroupBox.setObjectName(u"detailsGroupBox")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.detailsGroupBox.sizePolicy().hasHeightForWidth())
        self.detailsGroupBox.setSizePolicy(sizePolicy1)
        self.detailsGroupBox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalLayout = QVBoxLayout(self.detailsGroupBox)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalSpacer = QSpacerItem(178, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer)

        self.scPicture = QLabel(self.detailsGroupBox)
        self.scPicture.setObjectName(u"scPicture")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.scPicture.sizePolicy().hasHeightForWidth())
        self.scPicture.setSizePolicy(sizePolicy2)
        self.scPicture.setMaximumSize(QSize(426, 240))
        self.scPicture.setPixmap(QPixmap(u"I:/Wargames/Dragons of Glory/images/tales_cover.jpg"))
        self.scPicture.setScaledContents(True)

        self.horizontalLayout_2.addWidget(self.scPicture)

        self.horizontalSpacer_2 = QSpacerItem(178, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)


        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.scDescription = QTextEdit(self.detailsGroupBox)
        self.scDescription.setObjectName(u"scDescription")

        self.verticalLayout.addWidget(self.scDescription)

        self.detailsFrame = QFrame(self.detailsGroupBox)
        self.detailsFrame.setObjectName(u"detailsFrame")
        self.detailsFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.detailsFrame.setFrameShadow(QFrame.Shadow.Raised)
        self.gridLayout = QGridLayout(self.detailsFrame)
        self.gridLayout.setObjectName(u"gridLayout")
        self.notesButton = QPushButton(self.detailsFrame)
        self.notesButton.setObjectName(u"notesButton")

        self.gridLayout.addWidget(self.notesButton, 7, 3, 1, 1)

        self.hlVictory = QTextEdit(self.detailsFrame)
        self.hlVictory.setObjectName(u"hlVictory")
        self.hlVictory.setMaximumSize(QSize(263, 50))

        self.gridLayout.addWidget(self.hlVictory, 4, 0, 1, 3)

        self.wsVictory = QTextEdit(self.detailsFrame)
        self.wsVictory.setObjectName(u"wsVictory")
        self.wsVictory.setMaximumSize(QSize(263, 50))

        self.gridLayout.addWidget(self.wsVictory, 6, 0, 1, 3)

        self.lineEdit_3 = QLineEdit(self.detailsFrame)
        self.lineEdit_3.setObjectName(u"lineEdit_3")

        self.gridLayout.addWidget(self.lineEdit_3, 2, 1, 1, 2)

        self.hlCountries = QLineEdit(self.detailsFrame)
        self.hlCountries.setObjectName(u"hlCountries")

        self.gridLayout.addWidget(self.hlCountries, 3, 1, 1, 2)

        self.labelHL = QLabel(self.detailsFrame)
        self.labelHL.setObjectName(u"labelHL")

        self.gridLayout.addWidget(self.labelHL, 3, 0, 1, 1)

        self.labelOther = QLabel(self.detailsFrame)
        self.labelOther.setObjectName(u"labelOther")

        self.gridLayout.addWidget(self.labelOther, 4, 3, 1, 2)

        self.labelEnd = QLabel(self.detailsFrame)
        self.labelEnd.setObjectName(u"labelEnd")

        self.gridLayout.addWidget(self.labelEnd, 2, 0, 1, 1)

        self.lineEdit_2 = QLineEdit(self.detailsFrame)
        self.lineEdit_2.setObjectName(u"lineEdit_2")

        self.gridLayout.addWidget(self.lineEdit_2, 1, 4, 1, 1)

        self.startButton = QPushButton(self.detailsFrame)
        self.startButton.setObjectName(u"startButton")
        sizePolicy2.setHeightForWidth(self.startButton.sizePolicy().hasHeightForWidth())
        self.startButton.setSizePolicy(sizePolicy2)
        self.startButton.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.startButton.setAutoDefault(True)

        self.gridLayout.addWidget(self.startButton, 7, 2, 1, 1)

        self.lineEdit = QLineEdit(self.detailsFrame)
        self.lineEdit.setObjectName(u"lineEdit")

        self.gridLayout.addWidget(self.lineEdit, 1, 1, 1, 2)

        self.labelWS = QLabel(self.detailsFrame)
        self.labelWS.setObjectName(u"labelWS")

        self.gridLayout.addWidget(self.labelWS, 5, 0, 1, 2)

        self.labelInitiative = QLabel(self.detailsFrame)
        self.labelInitiative.setObjectName(u"labelInitiative")

        self.gridLayout.addWidget(self.labelInitiative, 1, 3, 1, 1)

        self.labelStart = QLabel(self.detailsFrame)
        self.labelStart.setObjectName(u"labelStart")

        self.gridLayout.addWidget(self.labelStart, 1, 0, 1, 1)

        self.wsCountries = QLineEdit(self.detailsFrame)
        self.wsCountries.setObjectName(u"wsCountries")

        self.gridLayout.addWidget(self.wsCountries, 5, 2, 1, 1)


        self.verticalLayout.addWidget(self.detailsFrame)


        self.horizontalLayout.addWidget(self.detailsGroupBox)


        self.retranslateUi(Dialog)

        QMetaObject.connectSlotsByName(Dialog)
    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"New Game", None))
        self.scGroupBox.setTitle(QCoreApplication.translate("Dialog", u"Scenarios", None))
        self.detailsGroupBox.setTitle(QCoreApplication.translate("Dialog", u"Scenario Details", None))
        self.scPicture.setText("")
        self.notesButton.setText(QCoreApplication.translate("Dialog", u"Notes", None))
        self.labelHL.setText(QCoreApplication.translate("Dialog", u"Highlord:", None))
        self.labelOther.setText(QCoreApplication.translate("Dialog", u"Other Info", None))
        self.labelEnd.setText(QCoreApplication.translate("Dialog", u"End:", None))
        self.startButton.setText(QCoreApplication.translate("Dialog", u"Start Game", None))
        self.labelWS.setText(QCoreApplication.translate("Dialog", u"Whitestone:", None))
        self.labelInitiative.setText(QCoreApplication.translate("Dialog", u"Initiative:", None))
        self.labelStart.setText(QCoreApplication.translate("Dialog", u"Start:", None))
    # retranslateUi

