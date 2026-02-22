import atexit
import faulthandler
import os
import signal
import sys
from collections import deque
from datetime import datetime

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

from src.content.config import LOG_FILE, LOGS_DIR


class RuntimeDiagnostics:
    """Lightweight runtime diagnostics for Qt/PySide crashes."""

    def __init__(self, logs_dir=LOGS_DIR, tail_file=LOG_FILE, recent_limit=200):
        self.logs_dir = logs_dir
        self.tail_file = tail_file
        self.recent_messages = deque(maxlen=recent_limit)
        self.qt_log_file = None
        self.installed = False

    def install(self):
        if self.installed:
            return
        enabled_raw = os.getenv("DOG_DIAGNOSTICS", "0").strip().lower()
        enabled = enabled_raw not in ("0", "false", "off", "no")
        if not enabled:
            return
        self.installed = True
        self._ensure_logs_dir()
        self._install_fault_handler()
        self._install_qt_logging()
        self._install_signal_handlers()
        self._install_exception_handler()
        atexit.register(self._write_qt_tail, "exit")

    def _ensure_logs_dir(self):
        os.makedirs(self.logs_dir, exist_ok=True)

    def _install_fault_handler(self):
        faulthandler.enable(all_threads=True)
        if hasattr(faulthandler, "register"):
            if hasattr(signal, "SIGABRT"):
                faulthandler.register(signal.SIGABRT, all_threads=True, chain=True)
            if hasattr(signal, "SIGSEGV"):
                faulthandler.register(signal.SIGSEGV, all_threads=True, chain=True)

    def _install_qt_logging(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(self.logs_dir, f"qt_runtime_{timestamp}.log")
        self.qt_log_file = open(log_path, "a", encoding="utf-8")

        def _qt_handler(mode, context, message):
            if mode in (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg):
                return

            mode_map = {
                QtMsgType.QtWarningMsg: "WARNING",
                QtMsgType.QtCriticalMsg: "CRITICAL",
                QtMsgType.QtFatalMsg: "FATAL",
            }
            level = mode_map.get(mode, "UNKNOWN")
            file_name = context.file if context and context.file else "?"
            line_no = context.line if context and context.line else 0
            function_name = context.function if context and context.function else "?"
            text = (
                f"[{datetime.now().isoformat(timespec='milliseconds')}] "
                f"{level} {file_name}:{line_no} {function_name} - {message}"
            )

            self.recent_messages.append(text)
            try:
                self.qt_log_file.write(text + "\n")
                self.qt_log_file.flush()
            except Exception:
                pass

            if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                print(text, file=sys.stderr, flush=True)

            if mode == QtMsgType.QtFatalMsg:
                self._write_qt_tail("qt_fatal")

        qInstallMessageHandler(_qt_handler)
        print(f"Qt runtime logging enabled: {log_path}")

    def _install_signal_handlers(self):
        for sig_name in ("SIGABRT", "SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self._on_termination_signal)
            except Exception:
                pass

    def _install_exception_handler(self):
        sys.excepthook = self._on_unhandled_exception

    def _write_qt_tail(self, reason="runtime"):
        try:
            lines = list(self.recent_messages)[-20:]
            with open(self.tail_file, "w", encoding="utf-8") as f:
                f.write(f"Reason: {reason}\n")
                f.write(f"Timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
                f.write("Last 20 Qt messages:\n")
                for line in lines:
                    f.write(line + "\n")
        except Exception:
            pass

    def _on_termination_signal(self, signum, _frame):
        self._write_qt_tail(reason=f"signal_{signum}")
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    def _on_unhandled_exception(self, exc_type, exc_value, tb):
        self._write_qt_tail(reason=f"unhandled_{getattr(exc_type, '__name__', str(exc_type))}")
        sys.__excepthook__(exc_type, exc_value, tb)
