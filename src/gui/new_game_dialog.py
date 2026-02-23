# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'new_game_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
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
from src.content.config import SCENARIOS_DIR, IMAGES_DIR
from src.content.loader import load_scenario_yaml
from src.content.text_formatter import TextFormatter
from src.gui.notes_dialog import NotesDialog
import os


class Ui_newGameDialog(object):
    def setupUi(self, newGameDialog):
        if not newGameDialog.objectName():
            newGameDialog.setObjectName(u"newGameDialog")
        newGameDialog.setWindowModality(Qt.WindowModality.NonModal)
        newGameDialog.resize(1024, 768)
        newGameDialog.setWindowOpacity(0.8)
        newGameDialog.setModal(True)
        self.horizontalLayout = QHBoxLayout(newGameDialog)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.scGroupBox = QGroupBox(newGameDialog)
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

        self.detailsGroupBox = QGroupBox(newGameDialog)
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
        self.horizontalSpacer = QSpacerItem(75, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer)

        self.scPicture = QLabel(self.detailsGroupBox)
        self.scPicture.setObjectName(u"scPicture")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.scPicture.sizePolicy().hasHeightForWidth())
        self.scPicture.setSizePolicy(sizePolicy2)
        self.scPicture.setMaximumSize(QSize(592, 333))
        self.scPicture.setStyleSheet(u"background: black")
        self.scPicture.setPixmap(QPixmap(IMAGES_DIR+'\\scenario.jpg'))
        self.scPicture.setScaledContents(True)

        self.horizontalLayout_2.addWidget(self.scPicture)

        self.horizontalSpacer_2 = QSpacerItem(75, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)


        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.scTitle = QLabel(self.detailsGroupBox)
        self.scTitle.setObjectName(u"scTitle")
        self.scTitle.setMaximumSize(QSize(16777215, 25))
        font = QFont()
        font.setFamilies([u"Libra"])
        font.setPointSize(20)
        self.scTitle.setFont(font)
        self.scTitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout.addWidget(self.scTitle)

        self.scDescription = QTextEdit(self.detailsGroupBox)
        self.scDescription.setObjectName(u"scDescription")
        font1 = QFont()
        font1.setPointSize(12)
        self.scDescription.setFont(font1)
        self.scDescription.setReadOnly(True)

        self.verticalLayout.addWidget(self.scDescription)

        self.detailsFrame = QFrame(self.detailsGroupBox)
        self.detailsFrame.setObjectName(u"detailsFrame")
        self.detailsFrame.setFrameShape(QFrame.Shape.StyledPanel)
        self.detailsFrame.setFrameShadow(QFrame.Shadow.Raised)
        self.gridLayout = QGridLayout(self.detailsFrame)
        self.gridLayout.setObjectName(u"gridLayout")
        self.startTurn = QLineEdit(self.detailsFrame)
        self.startTurn.setObjectName(u"startTurn")
        self.startTurn.setReadOnly(True)

        self.gridLayout.addWidget(self.startTurn, 1, 1, 1, 2)

        self.startButton = QPushButton(self.detailsFrame)
        self.startButton.setObjectName(u"startButton")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.startButton.sizePolicy().hasHeightForWidth())
        self.startButton.setSizePolicy(sizePolicy3)
        self.startButton.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.startButton.setAutoDefault(True)

        self.gridLayout.addWidget(self.startButton, 7, 2, 1, 1)

        self.labelHL = QLabel(self.detailsFrame)
        self.labelHL.setObjectName(u"labelHL")

        self.gridLayout.addWidget(self.labelHL, 3, 0, 1, 1)

        self.hlVictory = QTextEdit(self.detailsFrame)
        self.hlVictory.setObjectName(u"hlVictory")
        self.hlVictory.setMaximumSize(QSize(400, 50))
        self.hlVictory.setReadOnly(True)

        self.gridLayout.addWidget(self.hlVictory, 4, 0, 1, 3)

        self.hlCountries = QLineEdit(self.detailsFrame)
        self.hlCountries.setObjectName(u"hlCountries")
        self.hlCountries.setReadOnly(True)

        self.gridLayout.addWidget(self.hlCountries, 3, 1, 1, 2)

        self.labelStart = QLabel(self.detailsFrame)
        self.labelStart.setObjectName(u"labelStart")

        self.gridLayout.addWidget(self.labelStart, 1, 0, 1, 1)

        self.labelWS = QLabel(self.detailsFrame)
        self.labelWS.setObjectName(u"labelWS")

        self.gridLayout.addWidget(self.labelWS, 3, 3, 1, 1)

        self.wsCountries = QLineEdit(self.detailsFrame)
        self.wsCountries.setObjectName(u"wsCountries")
        self.wsCountries.setReadOnly(True)

        self.gridLayout.addWidget(self.wsCountries, 3, 4, 1, 1)

        self.wsVictory = QTextEdit(self.detailsFrame)
        self.wsVictory.setObjectName(u"wsVictory")
        self.wsVictory.setMaximumSize(QSize(400, 50))
        self.wsVictory.setReadOnly(True)

        self.gridLayout.addWidget(self.wsVictory, 4, 3, 1, 2)

        self.notesButton = QPushButton(self.detailsFrame)
        self.notesButton.setObjectName(u"notesButton")

        self.gridLayout.addWidget(self.notesButton, 7, 3, 1, 1)

        self.labelEnd = QLabel(self.detailsFrame)
        self.labelEnd.setObjectName(u"labelEnd")

        self.gridLayout.addWidget(self.labelEnd, 1, 3, 1, 1)

        self.labelInitiative = QLabel(self.detailsFrame)
        self.labelInitiative.setObjectName(u"labelInitiative")

        self.gridLayout.addWidget(self.labelInitiative, 2, 0, 1, 1)

        self.endTurn = QLineEdit(self.detailsFrame)
        self.endTurn.setObjectName(u"endTurn")
        self.endTurn.setReadOnly(True)

        self.gridLayout.addWidget(self.endTurn, 1, 4, 1, 1)

        self.initiative = QLineEdit(self.detailsFrame)
        self.initiative.setObjectName(u"initiative")
        self.initiative.setReadOnly(True)

        self.gridLayout.addWidget(self.initiative, 2, 1, 1, 2)


        self.verticalLayout.addWidget(self.detailsFrame)


        self.horizontalLayout.addWidget(self.detailsGroupBox)


        self.retranslateUi(newGameDialog)

        QMetaObject.connectSlotsByName(newGameDialog)
    # setupUi

    def retranslateUi(self, newGameDialog):
        newGameDialog.setWindowTitle(QCoreApplication.translate("newGameDialog", u"New Game", None))
        self.scGroupBox.setTitle(QCoreApplication.translate("newGameDialog", u"Scenarios", None))
        self.detailsGroupBox.setTitle(QCoreApplication.translate("newGameDialog", u"Scenario Details", None))
        self.scPicture.setText("")
        self.scTitle.setText(QCoreApplication.translate("newGameDialog", u"Scenario Title", None))
        self.startButton.setText(QCoreApplication.translate("newGameDialog", u"Start Game", None))
        self.labelHL.setText(QCoreApplication.translate("newGameDialog", u"Highlord:", None))
        self.labelStart.setText(QCoreApplication.translate("newGameDialog", u"Start:", None))
        self.labelWS.setText(QCoreApplication.translate("newGameDialog", u"Whitestone:", None))
        self.notesButton.setText(QCoreApplication.translate("newGameDialog", u"Notes", None))
        self.labelEnd.setText(QCoreApplication.translate("newGameDialog", u"End:", None))
        self.labelInitiative.setText(QCoreApplication.translate("newGameDialog", u"Initiative:", None))
    # retranslateUi


class NewGameDialog(QDialog):
    """
    Custom dialog class that wraps the auto-generated UI.
    Handles logic for loading and displaying scenario information.
    """
    
    def __init__(self, parent=None, translator=None):
        super().__init__(parent)
        self.ui = Ui_newGameDialog()
        self.ui.setupUi(self)
        
        self._current_scenario_spec = None
        self.translator = translator or getattr(parent, "translator", None)
        self.text_formatter = TextFormatter(self.translator) if self.translator else None
        
        # Connect signals
        self.ui.scListView.selectionModel().selectionChanged.connect(self._on_scenario_selected)
        self.ui.startButton.clicked.connect(self.accept)
        self.ui.notesButton.clicked.connect(self._on_notes_clicked)

    def _on_notes_clicked(self):
        """Open the notes dialog for the current scenario."""
        if not self._current_scenario_spec:
            return

        notes = getattr(self._current_scenario_spec, 'notes', "No notes available for this scenario.")
        dialog = NotesDialog(notes, self)
        dialog.exec()

    def _on_scenario_selected(self, selected, deselected):
        """Handle scenario selection from the list view."""
        indexes = selected.indexes()
        if not indexes:
            self._clear_details()
            return
            
        # Get the selected file path
        model = self.ui.scListView.model()
        file_path = model.filePath(indexes[0])
        
        # Load the scenario spec
        try:
            self._current_scenario_spec = load_scenario_yaml(file_path)
            self._display_scenario_details(self._current_scenario_spec)
        except Exception as e:
            print(f"Error loading scenario: {e}")
            self._clear_details()
    
    def _display_scenario_details(self, spec):
        """Display scenario details in the UI from the ScenarioSpec."""
        # Title (id)
        if self.translator:
            translated_title = self.translator.get_text("scenarios", spec.id)
            self.ui.scTitle.setText(translated_title)
        else:
            self.ui.scTitle.setText(spec.id)
        # Description
        self.ui.scDescription.setPlainText(spec.description)

        # Picture
        pic_filename = spec.picture if spec.picture else "scenario.jpg"
        pic_path = os.path.join(IMAGES_DIR, pic_filename)

        # Check if file exists, else use fallback or blank
        if os.path.exists(pic_path):
            self.ui.scPicture.setPixmap(QPixmap(pic_path))
        else:
            # Optional: Set a specific "missing image" placeholder if desired
            # For now, we can try loading the COVER_PICTURE from config as fallback
            from src.content.config import COVER_PICTURE
            if os.path.exists(COVER_PICTURE):
                self.ui.scPicture.setPixmap(QPixmap(COVER_PICTURE))
            else:
                self.ui.scPicture.clear()

        # Turn information
        self.ui.startTurn.setText(str(spec.start_turn))
        self.ui.endTurn.setText(str(spec.end_turn))
        self.ui.initiative.setText(spec.initiative_start.title())
        
        # Highlord countries
        hl_setup = spec.setup.get("highlord", {})
        hl_countries = list(hl_setup.get("countries", {}).keys())
        self.ui.hlCountries.setText(", ".join(c.title() for c in hl_countries) if hl_countries else "None")
        
        # Whitestone countries
        ws_setup = spec.setup.get("whitestone", {})
        ws_countries = list(ws_setup.get("countries", {}).keys())
        self.ui.wsCountries.setText(", ".join(c.title() for c in ws_countries) if ws_countries else "None")
        
        # Victory conditions
        vc = spec.victory_conditions
        hl_vc = vc.get("highlord", {})
        ws_vc = vc.get("whitestone", {})

        if self.text_formatter:
            self.ui.hlVictory.setPlainText(self.text_formatter.format_victory_conditions(hl_vc))
            self.ui.wsVictory.setPlainText(self.text_formatter.format_victory_conditions(ws_vc))
        else:
            self.ui.hlVictory.setPlainText(str(hl_vc))
            self.ui.wsVictory.setPlainText(str(ws_vc))
    
    def _clear_details(self):
        """Clear all detail fields."""
        self.ui.scDescription.clear()
        self.ui.startTurn.clear()
        self.ui.endTurn.clear()
        self.ui.initiative.clear()
        self.ui.hlCountries.clear()
        self.ui.wsCountries.clear()
        self.ui.hlVictory.clear()
        self.ui.wsVictory.clear()
        self._current_scenario_spec = None
    
    def get_selected_scenario_spec(self):
        """Returns the currently selected ScenarioSpec, or None if nothing is selected."""
        return self._current_scenario_spec
