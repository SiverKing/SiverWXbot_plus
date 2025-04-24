import sys
from typing import NoReturn
from PyQt6 import QtCore, QtWidgets
from MainWindow import MainWindow

"""
pyinstaller App.spec 
"""


def configure_application(app: QtWidgets.QApplication) -> None:
    app.setApplicationName("SiverBot")
    app.setApplicationDisplayName("SiverBot")
    app.setApplicationVersion("1.0.0")
    app.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def setup_main_window() -> MainWindow:
    window = MainWindow()
    window.setWindowTitle("SiverBot - 智能助手")
    window.setMinimumSize(1024, 768)
    screen_geometry = QtWidgets.QApplication.primaryScreen().availableGeometry()
    window.move(
        (screen_geometry.width() - window.width()) // 2,
        (screen_geometry.height() - window.height()) // 3
    )
    return window


def main() -> NoReturn:
    app = QtWidgets.QApplication(sys.argv)
    try:
        configure_application(app)
        main_window = setup_main_window()
        main_window.show()
        exit_code = app.exec()
    except Exception as e:
        print(f"Critical error occurred: {e}", file=sys.stderr)
        exit_code = 1
    finally:
        sys.exit(exit_code)


if __name__ == '__main__':
    main()
