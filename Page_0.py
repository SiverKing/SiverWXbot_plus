from PyQt6 import QtWidgets, QtCore
from Common import log
# from WxBot import WXBotThread
from wxbot_class import WXBot

class Page_0(QtWidgets.QWidget):
    def __init__(self, wx, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.wx = wx
        self.is_start = True
        self.connectSignal()
        self.bot_thread = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.time_counter = 0

    def connectSignal(self):
        self.parent.pushButton_start.clicked.connect(self.toggleState)

    def toggleState(self):
        if self.is_start:
            self.start_bot()
        else:
            self.stop_bot()
        self.is_start = not self.is_start

    def start_bot(self):
        log("INFO", "启动机器人")
        self.parent.pushButton_start.setText("停止")
        self.parent.pushButton_start.setStyleSheet("""
            QPushButton {
                background-color: rgba(205, 92, 92, 0.9);
                border-radius: 9px;
                border: none;
                padding: 8px 15px;
                min-width: 100px;
                color: #f0f0f0;
                transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }
            QPushButton:hover {
                background-color: rgba(220, 120, 120, 0.95);
                box-shadow: 0 4px 8px rgba(0,0,0,0.12);
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: rgba(185, 70, 70, 0.9);
                box-shadow: 0 1px 2px rgba(0,0,0,0.1);
                transform: translateY(1px);
            }
            QPushButton:disabled {
                background-color: rgba(215, 180, 180, 0.6);
                color: rgba(100, 100, 100, 0.8);
                box-shadow: none;
                cursor: not-allowed;
            }
            QPushButton:focus {
                outline: 2px solid rgba(205, 92, 92, 0.4);
                outline-offset: 2px;
            }
        """)
        if self.bot_thread and self.bot_thread.isRunning():
            log("INFO", "状态 机器人已在运行")
            return
        self.bot_thread = WXBot(parent=self)
        self.bot_thread.finished.connect(self.on_bot_finished)
        self.bot_thread.start()
        self.time_counter = 0
        self.timer.start(1000)
        self.update_timer()

    def stop_bot(self):
        log("WARNING", "停止机器人")
        if self.bot_thread:
            self.bot_thread.stop()
            self.bot_thread = None
        self.timer.stop()

    def on_bot_finished(self):
        self.parent.pushButton_start.setText("开启")
        self.parent.pushButton_start.setStyleSheet("""
            QPushButton {
                background-color: rgba(143, 188, 143, 0.9);
                border-radius: 9px;
                border: none;
                padding: 8px 15px;
                min-width: 100px;
                color: #f0f0f0;
                transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }
            QPushButton:hover {
                background-color: rgba(162, 205, 162, 0.95);
                box-shadow: 0 4px 8px rgba(0,0,0,0.12);
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: rgba(123, 168, 123, 0.9);
                box-shadow: 0 1px 2px rgba(0,0,0,0.1);
                transform: translateY(1px);
            }
            QPushButton:disabled {
                background-color: rgba(200, 215, 200, 0.6);
                color: rgba(100, 100, 100, 0.8);
                box-shadow: none;
                cursor: not-allowed;
            }
            QPushButton:focus {
                outline: 2px solid rgba(143, 188, 143, 0.4);
                outline-offset: 2px;
            }
        """)
        self.timer.stop()

    def update_timer(self):
        max_seconds = 3599999
        self.time_counter = min(self.time_counter + 1, max_seconds)
        time_text = "%03d:%02d:%02d" % (
        self.time_counter // 3600, (self.time_counter % 3600) // 60, self.time_counter % 60)
        self.parent.label_time.setText(time_text)
