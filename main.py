from PySide6.QtWidgets import QApplication
from app.guid_search import GuidSearchWindow
import sys

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GuidSearchWindow()
    window.show()
    sys.exit(app.exec())



