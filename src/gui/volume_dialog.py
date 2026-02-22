# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'volume_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QDialog,
    QDialogButtonBox, QGridLayout, QSizePolicy, QSlider,
    QWidget)

class Ui_volumeDialog(object):
    def setupUi(self, volumeDialog):
        if not volumeDialog.objectName():
            volumeDialog.setObjectName(u"volumeDialog")
        volumeDialog.setWindowModality(Qt.WindowModality.WindowModal)
        volumeDialog.resize(400, 122)
        self.gridLayout = QGridLayout(volumeDialog)
        self.gridLayout.setObjectName(u"gridLayout")

        # Common style for all checkboxes
        checkbox_style = """
            QCheckBox {
                font-size: 24pt;
                font-family: Libra;
            }
            QCheckBox::indicator {
                font-family: "Arial";
                font-size: 12px;
                font-weight: bold;
                width: 20px;
                height: 20px;
            }
        """

        # Music Checkbox
        self.musicVolCbx = QCheckBox(volumeDialog)
        self.musicVolCbx.setObjectName(u"musicVolCbx")
        self.musicVolCbx.setStyleSheet(checkbox_style)

        self.gridLayout.addWidget(self.musicVolCbx, 0, 0, 1, 1)

        # Music Slider
        self.musicVolume = QSlider(volumeDialog)
        self.musicVolume.setObjectName(u"musicVolume")
        self.musicVolume.setMaximum(100)
        self.musicVolume.setSliderPosition(100)
        self.musicVolume.setOrientation(Qt.Orientation.Horizontal)

        self.gridLayout.addWidget(self.musicVolume, 0, 1, 1, 1)

        # SFX Checkbox
        self.sndVolCbx = QCheckBox(volumeDialog)
        self.sndVolCbx.setObjectName(u"sndVolCbx")
        self.sndVolCbx.setStyleSheet(checkbox_style)

        self.gridLayout.addWidget(self.sndVolCbx, 1, 0, 1, 1)

        # SFX Slider
        self.soundVolume = QSlider(volumeDialog)
        self.soundVolume.setObjectName(u"soundVolume")
        self.soundVolume.setMaximum(100)
        self.soundVolume.setSliderPosition(100)
        self.soundVolume.setOrientation(Qt.Orientation.Horizontal)

        self.gridLayout.addWidget(self.soundVolume, 1, 1, 1, 1)

        self.volButtonBox = QDialogButtonBox(volumeDialog)
        self.volButtonBox.setObjectName(u"volButtonBox")
        self.volButtonBox.setOrientation(Qt.Orientation.Horizontal)
        self.volButtonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)
        self.volButtonBox.setCenterButtons(True)

        self.gridLayout.addWidget(self.volButtonBox, 2, 0, 1, 2)


        self.retranslateUi(volumeDialog)
        self.volButtonBox.accepted.connect(volumeDialog.accept)
        self.volButtonBox.rejected.connect(volumeDialog.reject)

        QMetaObject.connectSlotsByName(volumeDialog)
    # setupUi

    def retranslateUi(self, volumeDialog):
        volumeDialog.setWindowTitle(QCoreApplication.translate("volumeDialog", u"Audio Settings", None))
        self.musicVolCbx.setText(QCoreApplication.translate("volumeDialog", u"Music", None))
        self.sndVolCbx.setText(QCoreApplication.translate("volumeDialog", u"Sounds", None))
    # retranslateUi

