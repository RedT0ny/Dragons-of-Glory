# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'about.ui'
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
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QLabel,
    QSizePolicy, QTextBrowser, QVBoxLayout, QWidget)
from src.content.config import APP_NAME, APP_VERSION, COVER_PICTURE

ABOUT_HTML = """
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: "Segoe UI", sans-serif; font-size: 9pt; color: #0f1115; }}
    .mono {{ font-family: "Courier New", monospace; font-size: 10pt; }}
    h3 {{ margin: 12px 0 6px; }}
    p {{ margin: 6px 0; }}
    ul {{ margin: 6px 0 6px 18px; padding: 0; }}
    hr {{ border: none; border-top: 1px solid #0f1115; margin: 12px 0; }}
    a {{ color: #14427c; text-decoration: underline; }}
    .center {{ text-align: center; }}
  </style>
</head>
<body>
  <p>Version {app_version}</p>

  <p class="mono">{app_name} is a fan-made, non-profit adaptation of the classic Dragonlance module
     DL-11 “Dragons of Glory.”</p>

  <hr>

  <h3 class="mono">LEGAL &amp; COPYRIGHT INFORMATION</h3>

  <p class="mono">
    This game is unofficial Fan Content permitted under the Wizards of the Coast Fan Content Policy.
    It is not approved, endorsed, or sponsored by Wizards of the Coast LLC.
  </p>

  <p class="mono">Portions of the materials used are property of Wizards of the Coast LLC, including references to:</p>
  <ul class="mono">
    <li>Dragonlance®</li>
    <li>DL-11 “Dragons of Glory”</li>
    <li>TSR, Inc.</li>
  </ul>

  <p class="mono">
    DL-11 “Dragons of Glory” was published by TSR, Inc. in 1985 as part of the Dragonlance series of
    adventure modules. It featured a war game simulation of the War of the Lance in the Dragonlance
    campaign setting. It was created by:
  </p>
  <ul class="mono">
    <li>Douglas Niles</li>
    <li>Tracy Hickman</li>
    <li>Jeff Easley (cover artist)</li>
  </ul>

  <p class="mono">© Wizards of the Coast LLC. All Rights Reserved.</p>

  <hr>

  <h3 class="mono">Contact / Credits</h3>
  <p class="mono"><b>Creator</b>: <a href="mailto:redtony@gmail.com?subject=About DoG">Tony J. Soler</a></p>

  <hr>

  <h3 class="mono">Licensing</h3>
  <p class="mono">
    This game's original code is free software: you can redistribute it and/or modify it under the terms of the
    <a href="https://www.gnu.org/licenses/">GNU General Public License</a> as published by the Free Software Foundation,
    either version 3 of the License, or (at your option) any later version.
  </p>

  <p class="mono">
    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
    warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
    <a href="https://www.gnu.org/licenses/gpl-3.0.en.html">GNU General Public License v3.0</a> for more details.
  </p>

  <p class="mono center">--- <b>IMPORTANT NOTE</b> ---</p>

  <p class="mono">
    This license applies ONLY to the original code written by the game's author. The Dragonlance setting, DL-11 module
    content, and all related Wizards of the Coast intellectual property are NOT covered by this license and remain the
    exclusive property of Wizards of the Coast LLC.
  </p>
</body>
</html>
""".strip()

class Ui_aboutDialog(object):
    def setupUi(self, aboutDialog):
        if not aboutDialog.objectName():
            aboutDialog.setObjectName(u"aboutDialog")
        aboutDialog.resize(621, 1240)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(aboutDialog.sizePolicy().hasHeightForWidth())
        aboutDialog.setSizePolicy(sizePolicy)
        aboutDialog.setMaximumSize(QSize(960, 1400))
        self.verticalLayout = QVBoxLayout(aboutDialog)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.label = QLabel(aboutDialog)
        self.label.setObjectName(u"label")
        sizePolicy.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy)
        self.label.setMaximumSize(QSize(540, 360))
        self.label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.label.setFrameShape(QFrame.Shape.Panel)
        self.label.setFrameShadow(QFrame.Shadow.Sunken)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setPixmap(QPixmap(COVER_PICTURE))
        self.label.setScaledContents(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.textBrowser = QTextBrowser(aboutDialog)
        self.textBrowser.setObjectName(u"textBrowser")

        self.verticalLayout.addWidget(self.textBrowser)

        self.retranslateUi(aboutDialog)

        QMetaObject.connectSlotsByName(aboutDialog)
    # setupUi

    def retranslateUi(self, aboutDialog):
        aboutDialog.setWindowTitle(QCoreApplication.translate("aboutDialog", u"About", None))
        self.label.setText("")
        html = QCoreApplication.translate("aboutDialog", ABOUT_HTML.format(app_name=APP_NAME, app_version=APP_VERSION), None)
        self.textBrowser.setHtml(html)
    # retranslateUi

