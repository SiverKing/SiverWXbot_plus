from PyQt6 import QtWidgets, QtGui
from wxautox import WeChat

import Common
from Common import get_resource_path, log, is_online
from Page_0 import Page_0
from Page_1 import Page_1
from Ui_MainWindow import Ui_MainWindow

wx = None


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle("SiverBot")
        self.setWindowIcon(QtGui.QIcon(get_resource_path('resources/img/logo.ico')))
        Common.main_window = self
        self.base_url = None
        self.CONFIG_FILE = 'config.json'
        global wx
        self.init_wechat()
        self.page_0 = Page_0(wx, self)
        self.page_1 = Page_1(wx, self)

    def init_wechat(self):
        global wx
        try:
            wx = WeChat()
            self.label_Nickname.setText(wx.nickname)
            is_online(True)
            log("DEBUG", f"微信登录成功 {wx.nickname}")
            return True
        except:
            self.label_Nickname.setText("微信登录失败，请检查微信状态")
            is_online(False)
            log("ERROR", "微信登录失败，请检查微信状态")
            return False
