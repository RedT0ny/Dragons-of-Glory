# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'manual_viewer.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
                            QMetaObject, QObject, QPoint, QRect,
                            QSize, QTime, QUrl, Qt, QModelIndex, Slot, QStandardPaths, Signal, QPointF)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
                           QCursor, QFont, QFontDatabase, QGradient,
                           QIcon, QImage, QKeySequence, QLinearGradient,
                           QPainter, QPalette, QPixmap, QRadialGradient,
                           QTransform, QShortcut, QFontMetrics)
from PySide6.QtPdf import QPdfDocument, QPdfBookmarkModel, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (QApplication, QHeaderView, QListView, QMainWindow,
                               QMenu, QMenuBar, QSizePolicy, QSplitter,
                               QStatusBar, QTabWidget, QToolBar, QTreeView,
                               QVBoxLayout, QWidget, QSpinBox, QLineEdit, QMessageBox, QFileDialog, QDialog, QComboBox,
                               QStyledItemDelegate, QStyle)

from src.content.config import ZOOM_MULTIPLIER


class Ui_ManualViewer(object):
    def setupUi(self, ManualViewer):
        if not ManualViewer.objectName():
            ManualViewer.setObjectName(u"ManualViewer")
        ManualViewer.resize(700, 600)
        ManualViewer.setUnifiedTitleAndToolBarOnMac(True)
        self.actionOpen = QAction(ManualViewer)
        self.actionOpen.setObjectName(u"actionOpen")
        icon = QIcon(QIcon.fromTheme(u"document-open"))
        self.actionOpen.setIcon(icon)
        self.actionQuit = QAction(ManualViewer)
        self.actionQuit.setObjectName(u"actionQuit")
        icon1 = QIcon(QIcon.fromTheme(u"application-exit"))
        self.actionQuit.setIcon(icon1)
        self.actionAbout = QAction(ManualViewer)
        self.actionAbout.setObjectName(u"actionAbout")
        icon2 = QIcon(QIcon.fromTheme(u"help-about"))
        self.actionAbout.setIcon(icon2)
        self.actionAbout_Qt = QAction(ManualViewer)
        self.actionAbout_Qt.setObjectName(u"actionAbout_Qt")
        icon3 = QIcon(QIcon.fromTheme(QIcon.ThemeIcon.DialogInformation))
        self.actionAbout_Qt.setIcon(icon3)
        self.actionZoom_In = QAction(ManualViewer)
        self.actionZoom_In.setObjectName(u"actionZoom_In")
        icon4 = QIcon(QIcon.fromTheme(u"zoom-in"))
        self.actionZoom_In.setIcon(icon4)
        self.actionZoom_Out = QAction(ManualViewer)
        self.actionZoom_Out.setObjectName(u"actionZoom_Out")
        icon5 = QIcon(QIcon.fromTheme(u"zoom-out"))
        self.actionZoom_Out.setIcon(icon5)
        self.actionPrevious_Page = QAction(ManualViewer)
        self.actionPrevious_Page.setObjectName(u"actionPrevious_Page")
        icon6 = QIcon(QIcon.fromTheme(u"media-skip-backward"))
        self.actionPrevious_Page.setIcon(icon6)
        self.actionNext_Page = QAction(ManualViewer)
        self.actionNext_Page.setObjectName(u"actionNext_Page")
        icon7 = QIcon(QIcon.fromTheme(QIcon.ThemeIcon.MediaSkipForward))
        self.actionNext_Page.setIcon(icon7)
        self.actionContinuous = QAction(ManualViewer)
        self.actionContinuous.setObjectName(u"actionContinuous")
        self.actionContinuous.setCheckable(True)
        icon8 = QIcon(QIcon.fromTheme(QIcon.ThemeIcon.ZoomFitBest))
        self.actionContinuous.setIcon(icon8)
        self.actionBack = QAction(ManualViewer)
        self.actionBack.setObjectName(u"actionBack")
        self.actionBack.setEnabled(False)
        icon9 = QIcon(QIcon.fromTheme(QIcon.ThemeIcon.GoPrevious))
        self.actionBack.setIcon(icon9)
        self.actionForward = QAction(ManualViewer)
        self.actionForward.setObjectName(u"actionForward")
        self.actionForward.setEnabled(False)
        icon10 = QIcon(QIcon.fromTheme(QIcon.ThemeIcon.GoNext))
        self.actionForward.setIcon(icon10)
        self.actionFindNext = QAction(ManualViewer)
        self.actionFindNext.setObjectName(u"actionFindNext")
        icon11 = QIcon(QIcon.fromTheme(u"go-down"))
        self.actionFindNext.setIcon(icon11)
        self.actionFindPrevious = QAction(ManualViewer)
        self.actionFindPrevious.setObjectName(u"actionFindPrevious")
        icon12 = QIcon(QIcon.fromTheme(u"go-up"))
        self.actionFindPrevious.setIcon(icon12)
        self.centralWidget = QWidget(ManualViewer)
        self.centralWidget.setObjectName(u"centralWidget")
        self.verticalLayout = QVBoxLayout(self.centralWidget)
        self.verticalLayout.setSpacing(0)
        self.verticalLayout.setContentsMargins(11, 11, 11, 11)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.widget = QWidget(self.centralWidget)
        self.widget.setObjectName(u"widget")
        self.verticalLayout_2 = QVBoxLayout(self.widget)
        self.verticalLayout_2.setSpacing(0)
        self.verticalLayout_2.setContentsMargins(11, 11, 11, 11)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(self.widget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.tabWidget = QTabWidget(self.splitter)
        self.tabWidget.setObjectName(u"tabWidget")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.tabWidget.sizePolicy().hasHeightForWidth())
        self.tabWidget.setSizePolicy(sizePolicy)
        self.tabWidget.setTabPosition(QTabWidget.TabPosition.West)
        self.tabWidget.setDocumentMode(False)
        self.bookmarkTab = QWidget()
        self.bookmarkTab.setObjectName(u"bookmarkTab")
        self.verticalLayout_3 = QVBoxLayout(self.bookmarkTab)
        self.verticalLayout_3.setSpacing(0)
        self.verticalLayout_3.setContentsMargins(11, 11, 11, 11)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.verticalLayout_3.setContentsMargins(2, 2, 2, 2)
        self.bookmarkView = QTreeView(self.bookmarkTab)
        self.bookmarkView.setObjectName(u"bookmarkView")
        sizePolicy.setHeightForWidth(self.bookmarkView.sizePolicy().hasHeightForWidth())
        self.bookmarkView.setSizePolicy(sizePolicy)
        self.bookmarkView.setHeaderHidden(True)

        self.verticalLayout_3.addWidget(self.bookmarkView)

        self.tabWidget.addTab(self.bookmarkTab, "")
        self.pagesTab = QWidget()
        self.pagesTab.setObjectName(u"pagesTab")
        self.verticalLayout_4 = QVBoxLayout(self.pagesTab)
        self.verticalLayout_4.setSpacing(6)
        self.verticalLayout_4.setContentsMargins(11, 11, 11, 11)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.verticalLayout_4.setContentsMargins(2, 2, 2, 2)
        self.thumbnailsView = QListView(self.pagesTab)
        self.thumbnailsView.setObjectName(u"thumbnailsView")
        sizePolicy.setHeightForWidth(self.thumbnailsView.sizePolicy().hasHeightForWidth())
        self.thumbnailsView.setSizePolicy(sizePolicy)
        self.thumbnailsView.setIconSize(QSize(128, 128))
        self.thumbnailsView.setMovement(QListView.Movement.Static)
        self.thumbnailsView.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbnailsView.setViewMode(QListView.ViewMode.IconMode)

        self.verticalLayout_4.addWidget(self.thumbnailsView)

        self.tabWidget.addTab(self.pagesTab, "")
        self.searchResultsTab = QWidget()
        self.searchResultsTab.setObjectName(u"searchResultsTab")
        self.verticalLayout_5 = QVBoxLayout(self.searchResultsTab)
        self.verticalLayout_5.setSpacing(0)
        self.verticalLayout_5.setContentsMargins(11, 11, 11, 11)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.verticalLayout_5.setContentsMargins(2, 2, 2, 2)
        self.searchResultsView = QListView(self.searchResultsTab)
        self.searchResultsView.setObjectName(u"searchResultsView")
        self.searchResultsView.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.verticalLayout_5.addWidget(self.searchResultsView)

        self.tabWidget.addTab(self.searchResultsTab, "")
        self.splitter.addWidget(self.tabWidget)
        self.pdfView = QPdfView(self.splitter)
        self.pdfView.setObjectName(u"pdfView")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(10)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.pdfView.sizePolicy().hasHeightForWidth())
        self.pdfView.setSizePolicy(sizePolicy1)
        self.splitter.addWidget(self.pdfView)

        self.verticalLayout_2.addWidget(self.splitter)


        self.verticalLayout.addWidget(self.widget)

        ManualViewer.setCentralWidget(self.centralWidget)
        self.menuBar = QMenuBar(ManualViewer)
        self.menuBar.setObjectName(u"menuBar")
        self.menuBar.setGeometry(QRect(0, 0, 700, 33))
        self.menuFile = QMenu(self.menuBar)
        self.menuFile.setObjectName(u"menuFile")
        self.menuHelp = QMenu(self.menuBar)
        self.menuHelp.setObjectName(u"menuHelp")
        self.menuView = QMenu(self.menuBar)
        self.menuView.setObjectName(u"menuView")
        ManualViewer.setMenuBar(self.menuBar)
        self.mainToolBar = QToolBar(ManualViewer)
        self.mainToolBar.setObjectName(u"mainToolBar")
        self.mainToolBar.setMovable(False)
        self.mainToolBar.setFloatable(False)
        ManualViewer.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.mainToolBar)
        self.statusBar = QStatusBar(ManualViewer)
        self.statusBar.setObjectName(u"statusBar")
        ManualViewer.setStatusBar(self.statusBar)
        self.searchToolBar = QToolBar(ManualViewer)
        self.searchToolBar.setObjectName(u"searchToolBar")
        ManualViewer.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.searchToolBar)

        self.menuBar.addAction(self.menuFile.menuAction())
        self.menuBar.addAction(self.menuView.menuAction())
        self.menuBar.addAction(self.menuHelp.menuAction())
        self.menuFile.addAction(self.actionOpen)
        self.menuFile.addAction(self.actionQuit)
        self.menuHelp.addAction(self.actionAbout)
        self.menuHelp.addAction(self.actionAbout_Qt)
        self.menuView.addAction(self.actionZoom_In)
        self.menuView.addAction(self.actionZoom_Out)
        self.menuView.addAction(self.actionPrevious_Page)
        self.menuView.addAction(self.actionNext_Page)
        self.menuView.addSeparator()
        self.menuView.addAction(self.actionContinuous)
        self.mainToolBar.addAction(self.actionOpen)
        self.mainToolBar.addSeparator()
        self.mainToolBar.addAction(self.actionZoom_Out)
        self.mainToolBar.addAction(self.actionZoom_In)
        self.mainToolBar.addSeparator()
        self.mainToolBar.addAction(self.actionBack)
        self.mainToolBar.addAction(self.actionForward)
        self.searchToolBar.addAction(self.actionFindPrevious)
        self.searchToolBar.addAction(self.actionFindNext)

        self.retranslateUi(ManualViewer)

        self.tabWidget.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(ManualViewer)
    # setupUi

    def retranslateUi(self, ManualViewer):
        ManualViewer.setWindowTitle(QCoreApplication.translate("ManualViewer", u"PDF Viewer", None))
        self.actionOpen.setText(QCoreApplication.translate("ManualViewer", u"Open...", None))
#if QT_CONFIG(shortcut)
        self.actionOpen.setShortcut(QCoreApplication.translate("ManualViewer", u"Ctrl+O", None))
#endif // QT_CONFIG(shortcut)
        self.actionQuit.setText(QCoreApplication.translate("ManualViewer", u"Quit", None))
#if QT_CONFIG(shortcut)
        self.actionQuit.setShortcut(QCoreApplication.translate("ManualViewer", u"Ctrl+Q", None))
#endif // QT_CONFIG(shortcut)
        self.actionAbout.setText(QCoreApplication.translate("ManualViewer", u"About", None))
        self.actionAbout_Qt.setText(QCoreApplication.translate("ManualViewer", u"About Qt", None))
        self.actionZoom_In.setText(QCoreApplication.translate("ManualViewer", u"Zoom In", None))
#if QT_CONFIG(shortcut)
        self.actionZoom_In.setShortcut(QCoreApplication.translate("ManualViewer", u"Ctrl+=", None))
#endif // QT_CONFIG(shortcut)
        self.actionZoom_Out.setText(QCoreApplication.translate("ManualViewer", u"Zoom Out", None))
#if QT_CONFIG(shortcut)
        self.actionZoom_Out.setShortcut(QCoreApplication.translate("ManualViewer", u"Ctrl+-", None))
#endif // QT_CONFIG(shortcut)
        self.actionPrevious_Page.setText(QCoreApplication.translate("ManualViewer", u"Previous Page", None))
#if QT_CONFIG(shortcut)
        self.actionPrevious_Page.setShortcut(QCoreApplication.translate("ManualViewer", u"PgUp", None))
#endif // QT_CONFIG(shortcut)
        self.actionNext_Page.setText(QCoreApplication.translate("ManualViewer", u"Next Page", None))
#if QT_CONFIG(shortcut)
        self.actionNext_Page.setShortcut(QCoreApplication.translate("ManualViewer", u"PgDown", None))
#endif // QT_CONFIG(shortcut)
        self.actionContinuous.setText(QCoreApplication.translate("ManualViewer", u"Continuous", None))
        self.actionBack.setText(QCoreApplication.translate("ManualViewer", u"Back", None))
#if QT_CONFIG(tooltip)
        self.actionBack.setToolTip(QCoreApplication.translate("ManualViewer", u"back to previous view", None))
#endif // QT_CONFIG(tooltip)
        self.actionForward.setText(QCoreApplication.translate("ManualViewer", u"Forward", None))
#if QT_CONFIG(tooltip)
        self.actionForward.setToolTip(QCoreApplication.translate("ManualViewer", u"forward to next view", None))
#endif // QT_CONFIG(tooltip)
        self.actionFindNext.setText(QCoreApplication.translate("ManualViewer", u"Find Next", None))
#if QT_CONFIG(tooltip)
        self.actionFindNext.setToolTip(QCoreApplication.translate("ManualViewer", u"Find the next occurrence of the phrase", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(shortcut)
        self.actionFindNext.setShortcut(QCoreApplication.translate("ManualViewer", u"F3", None))
#endif // QT_CONFIG(shortcut)
        self.actionFindPrevious.setText(QCoreApplication.translate("ManualViewer", u"Find Previous", None))
#if QT_CONFIG(tooltip)
        self.actionFindPrevious.setToolTip(QCoreApplication.translate("ManualViewer", u"Find the previous occurrence of the phrase", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(shortcut)
        self.actionFindPrevious.setShortcut(QCoreApplication.translate("ManualViewer", u"Shift+F3", None))
#endif // QT_CONFIG(shortcut)
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.bookmarkTab), QCoreApplication.translate("ManualViewer", u"Bookmarks", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.pagesTab), QCoreApplication.translate("ManualViewer", u"Pages", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.searchResultsTab), QCoreApplication.translate("ManualViewer", u"Search Results", None))
        self.menuFile.setTitle(QCoreApplication.translate("ManualViewer", u"File", None))
        self.menuHelp.setTitle(QCoreApplication.translate("ManualViewer", u"Help", None))
        self.menuView.setTitle(QCoreApplication.translate("ManualViewer", u"View", None))
        self.searchToolBar.setWindowTitle(QCoreApplication.translate("ManualViewer", u"toolBar", None))
    # retranslateUi


# Copyright (C) 2022 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR BSD-3-Clause
class ManualViewer(QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_ManualViewer()
        self.m_zoomSelector = ZoomSelector(self)
        self.m_pageSelector = QSpinBox(self)
        self.m_document = QPdfDocument(self)
        self.m_fileDialog = None

        self.ui.setupUi(self)

        self.m_zoomSelector.setMaximumWidth(150)
        self.ui.mainToolBar.insertWidget(self.ui.actionZoom_In, self.m_zoomSelector)

        self.ui.mainToolBar.insertWidget(self.ui.actionForward, self.m_pageSelector)
        self.m_pageSelector.valueChanged.connect(self.page_selected)
        nav = self.ui.pdfView.pageNavigator()
        nav.currentPageChanged.connect(self.m_pageSelector.setValue)
        nav.backAvailableChanged.connect(self.ui.actionBack.setEnabled)
        nav.forwardAvailableChanged.connect(self.ui.actionForward.setEnabled)

        self.m_zoomSelector.zoom_mode_changed.connect(self.ui.pdfView.setZoomMode)
        self.m_zoomSelector.zoom_factor_changed.connect(self.ui.pdfView.setZoomFactor)
        self.m_zoomSelector.reset()

        bookmark_model = QPdfBookmarkModel(self)
        bookmark_model.setDocument(self.m_document)

        self.ui.bookmarkView.setModel(bookmark_model)
        self.ui.bookmarkView.activated.connect(self.bookmark_selected)

        self.ui.thumbnailsView.setModel(self.m_document.pageModel())

        self.ui.pdfView.setDocument(self.m_document)

        self.ui.pdfView.zoomFactorChanged.connect(self.m_zoomSelector.set_zoom_factor)

        self.m_searchModel = QPdfSearchModel(self)
        self.m_searchModel.setDocument(self.m_document)
        self.m_searchField = QLineEdit(self)

        self.ui.pdfView.setSearchModel(self.m_searchModel)
        self.ui.searchToolBar.insertWidget(self.ui.actionFindPrevious, self.m_searchField)
        self.m_findShortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.m_findShortcut.activated.connect(self.setSearchFocus)
        self.m_searchField.setPlaceholderText("Find in document")
        self.m_searchField.setMaximumWidth(400)
        self.m_searchField.textEdited.connect(self.searchTextChanged)
        self.ui.searchResultsView.setModel(self.m_searchModel)
        self.m_delegate = SearchResultDelegate(self)
        self.ui.searchResultsView.setItemDelegate(self.m_delegate)
        sel_model = self.ui.searchResultsView.selectionModel()
        sel_model.currentChanged.connect(self.searchResultSelected)

    @Slot()
    def setSearchFocus(self):
        self.m_searchField.setFocus(Qt.FocusReason.ShortcutFocusReason)

    @Slot()
    def searchTextChanged(self, text):
        self.m_searchModel.setSearchString(text)
        self.ui.tabWidget.setCurrentWidget(self.ui.searchResultsTab)

    @Slot(QModelIndex, QModelIndex)
    def searchResultSelected(self, current, previous):
        if not current.isValid():
            return
        page = current.data(QPdfSearchModel.Role.Page.value)
        location = current.data(QPdfSearchModel.Role.Location.value)
        self.ui.pdfView.pageNavigator().jump(page, location)
        self.ui.pdfView.setCurrentSearchResultIndex(current.row())

    @Slot(QUrl)
    def open(self, doc_location):
        if doc_location.isLocalFile():
            self.m_document.load(doc_location.toLocalFile())
            document_title = self.m_document.metaData(QPdfDocument.MetaDataField.Title)
            self.setWindowTitle(document_title if document_title else "PDF Viewer")
            self.page_selected(0)
            self.m_pageSelector.setMaximum(self.m_document.pageCount() - 1)
        else:
            message = f"{doc_location} is not a valid local file"
            QMessageBox.critical(self, "Failed to open", message)

    @Slot(QModelIndex)
    def bookmark_selected(self, index):
        if not index.isValid():
            return
        page = index.data(int(QPdfBookmarkModel.Role.Page))
        zoom_level = index.data(int(QPdfBookmarkModel.Role.Level))
        self.ui.pdfView.pageNavigator().jump(page, QPoint(), zoom_level)

    @Slot(int)
    def page_selected(self, page):
        nav = self.ui.pdfView.pageNavigator()
        nav.jump(page, QPoint(), nav.currentZoom())

    @Slot()
    def on_actionOpen_triggered(self):
        if not self.m_fileDialog:
            directory = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            self.m_fileDialog = QFileDialog(self, "Choose a PDF", directory)
            self.m_fileDialog.setAcceptMode(QFileDialog.AcceptOpen)
            self.m_fileDialog.setMimeTypeFilters(["application/pdf"])
        if self.m_fileDialog.exec() == QDialog.Accepted:
            to_open = self.m_fileDialog.selectedUrls()[0]
            if to_open.isValid():
                self.open(to_open)

    @Slot()
    def on_actionFindNext_triggered(self):
        next = self.ui.searchResultsView.currentIndex().row() + 1
        if next >= self.m_searchModel.rowCount(QModelIndex()):
            next = 0
        self.ui.searchResultsView.setCurrentIndex(self.m_searchModel.index(next))

    @Slot()
    def on_actionFindPrevious_triggered(self):
        prev = self.ui.searchResultsView.currentIndex().row() - 1
        if prev < 0:
            prev = self.m_searchModel.rowCount(QModelIndex()) - 1
        self.ui.searchResultsView.setCurrentIndex(self.m_searchModel.index(prev))

    @Slot()
    def on_actionQuit_triggered(self):
        self.close()

    @Slot()
    def on_actionAbout_triggered(self):
        QMessageBox.about(self, "About PdfViewer",
                          "An example using QPdfDocument")

    @Slot()
    def on_actionAbout_Qt_triggered(self):
        QMessageBox.aboutQt(self)

    @Slot()
    def on_actionZoom_In_triggered(self):
        factor = self.ui.pdfView.zoomFactor() * ZOOM_MULTIPLIER
        self.ui.pdfView.setZoomFactor(factor)

    @Slot()
    def on_actionZoom_Out_triggered(self):
        factor = self.ui.pdfView.zoomFactor() / ZOOM_MULTIPLIER
        self.ui.pdfView.setZoomFactor(factor)

    @Slot()
    def on_actionPrevious_Page_triggered(self):
        nav = self.ui.pdfView.pageNavigator()
        nav.jump(nav.currentPage() - 1, QPoint(), nav.currentZoom())

    @Slot()
    def on_actionNext_Page_triggered(self):
        nav = self.ui.pdfView.pageNavigator()
        nav.jump(nav.currentPage() + 1, QPoint(), nav.currentZoom())

    @Slot(QModelIndex)
    def on_thumbnailsView_activated(self, index):
        nav = self.ui.pdfView.pageNavigator()
        nav.jump(index.row(), QPointF(), nav.currentZoom())

    @Slot()
    def on_actionContinuous_triggered(self):
        cont_checked = self.ui.actionContinuous.isChecked()
        mode = QPdfView.PageMode.MultiPage if cont_checked else QPdfView.PageMode.SinglePage
        self.ui.pdfView.setPageMode(mode)

    @Slot()
    def on_actionBack_triggered(self):
        self.ui.pdfView.pageNavigator().back()

    @Slot()
    def on_actionForward_triggered(self):
        self.ui.pdfView.pageNavigator().forward()


class ZoomSelector(QComboBox):

    zoom_mode_changed = Signal(QPdfView.ZoomMode)
    zoom_factor_changed = Signal(float)

    def __init__(self, parent):
        super().__init__(parent)
        self.setEditable(True)

        self.addItem("Fit Width")
        self.addItem("Fit Page")
        self.addItem("12%")
        self.addItem("25%")
        self.addItem("33%")
        self.addItem("50%")
        self.addItem("66%")
        self.addItem("75%")
        self.addItem("100%")
        self.addItem("125%")
        self.addItem("150%")
        self.addItem("200%")
        self.addItem("400%")

        self.currentTextChanged.connect(self.on_current_text_changed)
        self.lineEdit().editingFinished.connect(self._editing_finished)

    @Slot(float)
    def set_zoom_factor(self, zoomFactor):
        percent = int(zoomFactor * 100)
        self.setCurrentText(f"{percent}%")

    @Slot()
    def reset(self):
        self.setCurrentIndex(8)  # 100%

    @Slot(str)
    def on_current_text_changed(self, text):
        if text == "Fit Width":
            self.zoom_mode_changed.emit(QPdfView.ZoomMode.FitToWidth)
        elif text == "Fit Page":
            self.zoom_mode_changed.emit(QPdfView.ZoomMode.FitInView)
        elif text.endswith("%"):
            factor = 1.0
            zoom_level = int(text[:-1])
            factor = zoom_level / 100.0
            self.zoom_mode_changed.emit(QPdfView.ZoomMode.Custom)
            self.zoom_factor_changed.emit(factor)

    @Slot()
    def _editing_finished(self):
        self.on_current_text_changed(self.lineEdit().text())


class SearchResultDelegate(QStyledItemDelegate):

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter, option, index):
        displayText = index.data()
        boldBegin = displayText.find("<b>") + 3
        boldEnd = displayText.find("</b>", boldBegin)
        if boldBegin >= 3 and boldEnd > boldBegin:
            page = index.data(QPdfSearchModel.Role.Page.value)
            pageLabel = f"Page {page}: "
            boldText = displayText[boldBegin:boldEnd]
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())
            defaultFont = painter.font()
            fm = painter.fontMetrics()
            pageLabelWidth = fm.horizontalAdvance(pageLabel)
            yOffset = (option.rect.height() - fm.height()) / 2 + fm.ascent()
            painter.drawText(0, option.rect.y() + yOffset, pageLabel)
            boldFont = QFont(defaultFont)
            boldFont.setBold(True)
            boldWidth = QFontMetrics(boldFont).horizontalAdvance(boldText)
            prefixSuffixWidth = (option.rect.width() - pageLabelWidth - boldWidth) / 2
            painter.setFont(boldFont)
            painter.drawText(pageLabelWidth + prefixSuffixWidth, option.rect.y() + yOffset,
                             boldText)
            painter.setFont(defaultFont)
            suffix = fm.elidedText(displayText[boldEnd + 4:],
                                   Qt.TextElideMode.ElideRight, prefixSuffixWidth)
            painter.drawText(pageLabelWidth + prefixSuffixWidth + boldWidth,
                             option.rect.y() + yOffset, suffix)
            prefix = fm.elidedText(displayText[0:boldBegin - 3],
                                   Qt.TextElideMode.ElideLeft, prefixSuffixWidth)
            painter.drawText(pageLabelWidth + prefixSuffixWidth - fm.horizontalAdvance(prefix),
                             option.rect.y() + yOffset, prefix)
        else:
            super().paint(painter, option, index)