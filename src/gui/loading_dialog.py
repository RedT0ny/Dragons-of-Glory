from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog


class LoadingDialog:
    """Small modal progress dialog for coarse startup/load milestones."""

    def __init__(self, parent=None, title: str = "Loading", maximum: int = 100):
        self._closed = False
        self.dialog = QProgressDialog("", None, 0, maximum, parent)
        self.dialog.setWindowTitle(title)
        self.dialog.setWindowModality(Qt.ApplicationModal)
        self.dialog.setCancelButton(None)
        self.dialog.setMinimumDuration(0)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setValue(0)
        self.dialog.show()
        QApplication.processEvents()

    def step(self, text: str, value: int):
        self.dialog.setLabelText(text)
        self.dialog.setValue(value)
        QApplication.processEvents()

    def set_status(self, text: str, value: int):
        self.dialog.setLabelText(text)
        self.dialog.setValue(value)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.dialog.setValue(self.dialog.maximum())
        QApplication.processEvents()
        self.dialog.close()
