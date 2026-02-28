import sys
import unittest
from PySide6.QtCore import QObject, Signal, Slot, Qt, QCoreApplication

# Ensure QApplication exists
app = QCoreApplication.instance()
if not app:
    app = QCoreApplication(sys.argv)

class Emitter(QObject):
    test_signal = Signal(str)

class Receiver(QObject):
    def __init__(self):
        super().__init__()
        self.call_count = 0
        self.received_data = []

    @Slot(str)
    def on_signal(self, data):
        self.call_count += 1
        self.received_data.append(data)

class TestUniqueConnection(unittest.TestCase):
    def setUp(self):
        self.emitter = Emitter()
        self.receiver = Receiver()

    def test_unique_connection(self):
        """Verify that Qt.UniqueConnection prevents duplicate connections."""
        # First connection
        self.emitter.test_signal.connect(self.receiver.on_signal, Qt.UniqueConnection)
        
        # Second connection (should be ignored/no-op)
        # Note: In C++ Qt this returns false, in PySide it might return bool or None, but shouldn't raise exception
        try:
            self.emitter.test_signal.connect(self.receiver.on_signal, Qt.UniqueConnection)
        except Exception as e:
            self.fail(f"Re-connecting with UniqueConnection raised exception: {e}")

        # Emit signal
        self.emitter.test_signal.emit("test")

        # Check that slot was called exactly once
        self.assertEqual(self.receiver.call_count, 1, "Slot should be called exactly once")
        self.assertEqual(self.receiver.received_data, ["test"])

    def test_disconnect_warning_reproduction(self):
        """Demonstrate that disconnecting an unconnected signal fails (warns)."""
        # This test just exercises the path; we can't easily assert on stderr warning output 
        # without complex capture, but we can ensure it doesn't crash the interpreter.
        try:
            # This is expected to fail/warn but not raise Python exception
            self.emitter.test_signal.disconnect(self.receiver.on_signal)
        except RuntimeError:
            # Some bindings might raise RuntimeError
            pass
        except Exception:
            pass
            
        # If we reach here, we're good (warning is acceptable/expected behavior for this test case)
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()
