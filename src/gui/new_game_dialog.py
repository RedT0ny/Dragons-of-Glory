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
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListView, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpacerItem, QTextEdit, QVBoxLayout,
    QWidget)

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(1280, 720)
        self.horizontalLayout = QHBoxLayout(Dialog)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.scenarioGroupBox = QGroupBox(Dialog)
        self.scenarioGroupBox.setObjectName(u"scenarioGroupBox")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.scenarioGroupBox.sizePolicy().hasHeightForWidth())
        self.scenarioGroupBox.setSizePolicy(sizePolicy)
        self.scenarioGroupBox.setMinimumSize(QSize(400, 0))
        self.scenarioGroupBox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.formLayout = QFormLayout(self.scenarioGroupBox)
        self.formLayout.setObjectName(u"formLayout")
        self.listView = QListView(self.scenarioGroupBox)
        self.listView.setObjectName(u"listView")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.SpanningRole, self.listView)


        self.horizontalLayout.addWidget(self.scenarioGroupBox)

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

        self.scenarioPicLabel = QLabel(self.detailsGroupBox)
        self.scenarioPicLabel.setObjectName(u"scenarioPicLabel")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.scenarioPicLabel.sizePolicy().hasHeightForWidth())
        self.scenarioPicLabel.setSizePolicy(sizePolicy2)
        self.scenarioPicLabel.setMaximumSize(QSize(426, 240))
        self.scenarioPicLabel.setPixmap(QPixmap(u"I:/Wargames/Dragons of Glory/images/tales_cover.jpg"))
        self.scenarioPicLabel.setScaledContents(True)

        self.horizontalLayout_2.addWidget(self.scenarioPicLabel)

        self.horizontalSpacer_2 = QSpacerItem(178, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)


        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.descTextEdit = QPlainTextEdit(self.detailsGroupBox)
        self.descTextEdit.setObjectName(u"descTextEdit")

        self.verticalLayout.addWidget(self.descTextEdit)

        self.detailsFrame = QFrame(self.detailsGroupBox)
        self.detailsFrame.setObjectName(u"detailsFrame")
        self.detailsFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.detailsFrame.setFrameShadow(QFrame.Shadow.Raised)
        self.gridLayout = QGridLayout(self.detailsFrame)
        self.gridLayout.setObjectName(u"gridLayout")
        self.pushButton_2 = QPushButton(self.detailsFrame)
        self.pushButton_2.setObjectName(u"pushButton_2")

        self.gridLayout.addWidget(self.pushButton_2, 7, 3, 1, 1)

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

        self.label_4 = QLabel(self.detailsFrame)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout.addWidget(self.label_4, 3, 0, 1, 1)

        self.label_6 = QLabel(self.detailsFrame)
        self.label_6.setObjectName(u"label_6")

        self.gridLayout.addWidget(self.label_6, 4, 3, 1, 2)

        self.label_2 = QLabel(self.detailsFrame)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout.addWidget(self.label_2, 2, 0, 1, 1)

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

        self.label_5 = QLabel(self.detailsFrame)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout.addWidget(self.label_5, 5, 0, 1, 2)

        self.label_3 = QLabel(self.detailsFrame)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout.addWidget(self.label_3, 1, 3, 1, 1)

        self.label = QLabel(self.detailsFrame)
        self.label.setObjectName(u"label")

        self.gridLayout.addWidget(self.label, 1, 0, 1, 1)

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
        self.scenarioGroupBox.setTitle(QCoreApplication.translate("Dialog", u"Scenarios", None))
        self.detailsGroupBox.setTitle(QCoreApplication.translate("Dialog", u"Scenario Details", None))
        self.scenarioPicLabel.setText("")
        self.pushButton_2.setText(QCoreApplication.translate("Dialog", u"Notes", None))
        self.label_4.setText(QCoreApplication.translate("Dialog", u"Highlord:", None))
        self.label_6.setText(QCoreApplication.translate("Dialog", u"Other Info", None))
        self.label_2.setText(QCoreApplication.translate("Dialog", u"End:", None))
        self.startButton.setText(QCoreApplication.translate("Dialog", u"Start Game", None))
        self.label_5.setText(QCoreApplication.translate("Dialog", u"Whitestone:", None))
        self.label_3.setText(QCoreApplication.translate("Dialog", u"Initiative:", None))
        self.label.setText(QCoreApplication.translate("Dialog", u"Start:", None))
    # retranslateUi

