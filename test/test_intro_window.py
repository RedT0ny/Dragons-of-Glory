import sys
import os

# Add the project root to sys.path so we can import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from src.gui.intro_window import IntroWindow

class MockTranslator:
    """A simple mock translator for testing the UI without external data dependencies."""
    def get_text(self, category, key):
        # Maps the internal keys to display strings for the test
        translations = {
            "menu_continue": "Continue",
            "menu_new_game": "New Game",
            "menu_settings": "Settings",
            "menu_quit": "Quit",
            "app_name": "Dragons of Glory"
        }
        return translations.get(key, key)

def run_test():
    app = QApplication(sys.argv)
    
    # 1. Load the Libra Regular.otf font
    font_path = os.path.join("assets", "font", "Libra Regular.otf")
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            print(f"Successfully loaded font: {families}")
        else:
            print("Failed to load font file (format error).")
    else:
        print(f"Note: Font file not found at {font_path}. Using system default.")

    # 2. Initialize and show window
    translator = MockTranslator()
    window = IntroWindow(translator)
    window.show()

    print("Intro Window launched. Close the window to end the test.")
    sys.exit(app.exec())

if __name__ == "__main__":
    run_test()
