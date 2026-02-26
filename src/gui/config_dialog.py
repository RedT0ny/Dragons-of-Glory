# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'config_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QGridLayout, QGroupBox, QLabel,
    QSizePolicy, QWidget)
from src.content.translator import Translator

class Ui_configDialog(object):
    def setupUi(self, configDialog):
        if not configDialog.objectName():
            configDialog.setObjectName(u"configDialog")
        configDialog.resize(330, 330)
        self.gridLayout = QGridLayout(configDialog)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gameOptions = QGroupBox(configDialog)
        self.gameOptions.setObjectName(u"gameOptions")
        self.gridLayout_3 = QGridLayout(self.gameOptions)
        self.gridLayout_3.setObjectName(u"gridLayout_3")
        self.diffLabel = QLabel(self.gameOptions)
        self.diffLabel.setObjectName(u"diffLabel")
        font = QFont()
        font.setBold(True)
        self.diffLabel.setFont(font)

        self.gridLayout_3.addWidget(self.diffLabel, 0, 0, 1, 1)

        self.diffComboBox = QComboBox(self.gameOptions)
        self.diffComboBox.addItem("")
        self.diffComboBox.addItem("")
        self.diffComboBox.addItem("")
        self.diffComboBox.setObjectName(u"diffComboBox")

        self.gridLayout_3.addWidget(self.diffComboBox, 0, 1, 1, 1)

        self.cdLabel = QLabel(self.gameOptions)
        self.cdLabel.setObjectName(u"cdLabel")
        self.cdLabel.setFont(font)

        self.gridLayout_3.addWidget(self.cdLabel, 1, 0, 1, 1)

        self.cdComboBox = QComboBox(self.gameOptions)
        self.cdComboBox.addItem("")
        self.cdComboBox.addItem("")
        self.cdComboBox.setObjectName(u"cdComboBox")

        self.gridLayout_3.addWidget(self.cdComboBox, 1, 1, 1, 1)


        self.gridLayout.addWidget(self.gameOptions, 0, 0, 1, 1)

        self.playerConfig = QGroupBox(configDialog)
        self.playerConfig.setObjectName(u"playerConfig")
        self.gridLayout_2 = QGridLayout(self.playerConfig)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.wsControlLabel = QLabel(self.playerConfig)
        self.wsControlLabel.setObjectName(u"wsControlLabel")
        self.wsControlLabel.setFont(font)

        self.gridLayout_2.addWidget(self.wsControlLabel, 0, 0, 1, 1)

        self.wsComboBox = QComboBox(self.playerConfig)
        self.wsComboBox.addItem("")
        self.wsComboBox.addItem("")
        self.wsComboBox.setObjectName(u"wsComboBox")

        self.gridLayout_2.addWidget(self.wsComboBox, 0, 1, 1, 1)

        self.hlControlLabel = QLabel(self.playerConfig)
        self.hlControlLabel.setObjectName(u"hlControlLabel")
        self.hlControlLabel.setFont(font)

        self.gridLayout_2.addWidget(self.hlControlLabel, 1, 0, 1, 1)

        self.hlComboBox = QComboBox(self.playerConfig)
        self.hlComboBox.addItem("")
        self.hlComboBox.addItem("")
        self.hlComboBox.setObjectName(u"hlComboBox")

        self.gridLayout_2.addWidget(self.hlComboBox, 1, 1, 1, 1)


        self.gridLayout.addWidget(self.playerConfig, 1, 0, 1, 1)

        self.buttonBox = QDialogButtonBox(configDialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)

        self.gridLayout.addWidget(self.buttonBox, 2, 0, 1, 1, Qt.AlignmentFlag.AlignHCenter)


        self.retranslateUi(configDialog)
        self.buttonBox.accepted.connect(configDialog.accept)
        self.buttonBox.rejected.connect(configDialog.reject)

        QMetaObject.connectSlotsByName(configDialog)
    # setupUi

    def retranslateUi(self, configDialog):
        configDialog.setWindowTitle(QCoreApplication.translate("configDialog", u"Select sides", None))
        self.gameOptions.setTitle(QCoreApplication.translate("configDialog", u"Game options", None))
        self.diffLabel.setText(QCoreApplication.translate("configDialog", u"Difficulty", None))
        self.diffComboBox.setItemText(0, QCoreApplication.translate("configDialog", u"Easy", None))
        self.diffComboBox.setItemText(1, QCoreApplication.translate("configDialog", u"Normal", None))
        self.diffComboBox.setItemText(2, QCoreApplication.translate("configDialog", u"Hard", None))

        self.cdLabel.setText(QCoreApplication.translate("configDialog", u"Combat details", None))
        self.cdComboBox.setItemText(0, QCoreApplication.translate("configDialog", u"Brief", None))
        self.cdComboBox.setItemText(1, QCoreApplication.translate("configDialog", u"Verbose", None))

        self.playerConfig.setTitle(QCoreApplication.translate("configDialog", u"Player config", None))
        self.wsControlLabel.setText(QCoreApplication.translate("configDialog", u"Whitestone", None))
        self.wsComboBox.setItemText(0, QCoreApplication.translate("configDialog", u"Human", None))
        self.wsComboBox.setItemText(1, QCoreApplication.translate("configDialog", u"AI", None))

        self.hlControlLabel.setText(QCoreApplication.translate("configDialog", u"Highlord", None))
        self.hlComboBox.setItemText(0, QCoreApplication.translate("configDialog", u"Human", None))
        self.hlComboBox.setItemText(1, QCoreApplication.translate("configDialog", u"AI", None))

    # retranslateUi

class ConfigDialog(QDialog):
    """
    Game configuration dialog allowing the user to select game options and player configurations.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_configDialog()
        self.ui.setupUi(self)
        self.translator = Translator()
        self._apply_translations()

    def _apply_translations(self):
        tr = self.translator.tr
        self.setWindowTitle(tr("dialogs.config.title", "Select sides"))
        self.ui.gameOptions.setTitle(tr("dialogs.config.game_options", "Game options"))
        self.ui.diffLabel.setText(tr("dialogs.config.difficulty", "Difficulty"))
        self.ui.cdLabel.setText(tr("dialogs.config.combat_details", "Combat details"))
        self.ui.playerConfig.setTitle(tr("dialogs.config.player_config", "Player config"))
        self.ui.wsControlLabel.setText(tr("ui.whitestone", "Whitestone"))
        self.ui.hlControlLabel.setText(tr("ui.highlord", "Highlord"))

        self.ui.diffComboBox.clear()
        self.ui.diffComboBox.addItem(tr("dialogs.config.difficulty_easy", "Easy"), "easy")
        self.ui.diffComboBox.addItem(tr("dialogs.config.difficulty_normal", "Normal"), "normal")
        self.ui.diffComboBox.addItem(tr("dialogs.config.difficulty_hard", "Hard"), "hard")

        self.ui.cdComboBox.clear()
        self.ui.cdComboBox.addItem(tr("dialogs.config.combat_brief", "Brief"), "brief")
        self.ui.cdComboBox.addItem(tr("dialogs.config.combat_verbose", "Verbose"), "verbose")

        self.ui.hlComboBox.clear()
        self.ui.hlComboBox.addItem(tr("dialogs.config.human", "Human"), "human")
        self.ui.hlComboBox.addItem(tr("dialogs.config.ai", "AI"), "ai")

        self.ui.wsComboBox.clear()
        self.ui.wsComboBox.addItem(tr("dialogs.config.human", "Human"), "human")
        self.ui.wsComboBox.addItem(tr("dialogs.config.ai", "AI"), "ai")

        ok_btn = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn:
            ok_btn.setText(tr("dialogs.common.ok", "OK"))
        if cancel_btn:
            cancel_btn.setText(tr("dialogs.common.cancel", "Cancel"))

    def set_from_config(self, config: dict):
        difficulty = str(config.get("difficulty", "normal")).strip().lower()
        combat_details = str(config.get("combat_details", "brief")).strip().lower()
        hl_is_ai = bool(config.get("highlord_ai", False))
        ws_is_ai = bool(config.get("whitestone_ai", False))
        diff_idx = self.ui.diffComboBox.findData(difficulty if difficulty in {"easy", "normal", "hard"} else "normal")
        if diff_idx >= 0:
            self.ui.diffComboBox.setCurrentIndex(diff_idx)
        cd_idx = self.ui.cdComboBox.findData("verbose" if combat_details == "verbose" else "brief")
        if cd_idx >= 0:
            self.ui.cdComboBox.setCurrentIndex(cd_idx)
        hl_idx = self.ui.hlComboBox.findData("ai" if hl_is_ai else "human")
        if hl_idx >= 0:
            self.ui.hlComboBox.setCurrentIndex(hl_idx)
        ws_idx = self.ui.wsComboBox.findData("ai" if ws_is_ai else "human")
        if ws_idx >= 0:
            self.ui.wsComboBox.setCurrentIndex(ws_idx)

    def get_config(self):
        difficulty_text = str(self.ui.diffComboBox.currentData() or "normal")
        combat_details_text = str(self.ui.cdComboBox.currentData() or "brief")
        player_config = self.get_player_config()
        player_config["difficulty"] = difficulty_text
        player_config["combat_details"] = combat_details_text
        return player_config

    def get_player_config(self):
        """
        Returns a dictionary mapping side to AI status (True for AI, False for Human).
        """
        # Logic depends on your UI layout, assuming QComboBox or QRadioButton
        # Example assuming 'hlTypeCombo' and 'wsTypeCombo' exist in your UI
        hl_is_ai = str(self.ui.hlComboBox.currentData() or "human") == "ai"
        ws_is_ai = str(self.ui.wsComboBox.currentData() or "human") == "ai"

        return {
            "highlord_ai": hl_is_ai,
            "whitestone_ai": ws_is_ai
        }

    def get_game_options(self):
        """
        Returns a dictionary of selected game options, e.g. difficulty and combat details.
        """
        difficulty = str(self.ui.diffComboBox.currentData() or "normal")
        combat_details = str(self.ui.cdComboBox.currentData() or "brief")

        return {
            "difficulty": difficulty,
            "combat_details": combat_details
        }
