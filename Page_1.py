from PyQt6 import QtWidgets
from Common import read_config, update_config_value, log

class Page_1(QtWidgets.QWidget):
    def __init__(self, wx, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.wx = wx
        self.friend_list = []
        self.room_list = []
        self.greet_list = []
        self.data = {}
        self.setup_signals()
        self.init_user_and_room_lists()
        self.update_ui_from_data()
        self.set_checkbox_states()
        for checkbox in ["checkBox_Global_listen", "checkBox_listen_room", "checkBox_only_at", "checkBox_send_welcome", "checkBox_consent_Apply"]:
            getattr(self.parent, checkbox).stateChanged.connect(self.update_checkbox_state)
        if self.data.get("AllListen_switch"):
            self.parent.checkBox_listen_room.setChecked(True)
            self.parent.label_listen_friends_list.setText("排除监听的用户")

    def setup_signals(self):
        controls = [
            ("toolButton_addItem_friend", self.addItem_friends),
            ("toolButton_delItem_friend", self.delItem_friends),
            ("toolButton_addItem_room", self.addItem_room),
            ("toolButton_delItem_room", self.delItem_room),
            ("pushButton_add_greet", self.addGreet),
            ("pushButton_del_greet", self.delGreet),
            ("pushButton_save", self.save_config),
            ("pushButton_load", self.load_config)
        ]
        for control_name, method in controls:
            getattr(self.parent, control_name).clicked.connect(method)

    def addItem_friends(self):
        text, ok = QtWidgets.QInputDialog.getText(self, '输入好友备注', '请输入好友备注:')
        if ok and text:
            self.update_list_and_config(self.parent.listWidget_listen_friends_list, self.friend_list, 'listen_list', text)

    def delItem_friends(self):
        self.delete_items(self.parent.listWidget_listen_friends_list, self.friend_list, 'listen_list')

    def addItem_room(self):
        text, ok = QtWidgets.QInputDialog.getText(self, '输入群聊名称', '请输入群聊名称:')
        if ok and text:
            self.update_list_and_config(self.parent.listWidget_listen_room_list, self.room_list, 'group', text)

    def delItem_room(self):
        self.delete_items(self.parent.listWidget_listen_room_list, self.room_list, 'group')

    def init_user_and_room_lists(self):
        self.data = read_config()
        self.init_list_from_data("listen_list", self.friend_list, self.parent.listWidget_listen_friends_list)
        self.init_list_from_data("group", self.room_list, self.parent.listWidget_listen_room_list)

    def set_checkbox_states(self):
        self.parent.checkBox_Global_listen.setChecked(self.data.get("AllListen_switch", False))
        self.parent.checkBox_listen_room.setChecked(self.data.get("group_switch", False))
        self.parent.checkBox_only_at.setChecked(self.data.get("group_reply_at", False))
        self.parent.checkBox_send_welcome.setChecked(self.data.get("group_welcome", False))
        self.parent.checkBox_consent_Apply.setChecked(self.data.get("new_friend_switch", False))

    def update_checkbox_state(self, state):
        sender = self.sender()
        checkbox_name = sender.objectName()
        config_key = {'checkBox_Global_listen': 'AllListen_switch',
                      'checkBox_listen_room': 'group_switch',
                      'checkBox_only_at': 'group_reply_at',
                      'checkBox_send_welcome': 'group_welcome',
                      'checkBox_consent_Apply': 'new_friend_switch'}.get(checkbox_name)
        update_config_value(config_key, bool(state))
        if checkbox_name == "checkBox_Global_listen":
            if bool(state):
                self.parent.checkBox_listen_room.setChecked(True)
                self.parent.label_listen_friends_list.setText("排除监听的用户")
            else:
                self.parent.label_listen_friends_list.setText("监听用户")

    def addGreet(self):
        text, ok = QtWidgets.QInputDialog.getMultiLineText(self, '输入打招呼话术', '请输入打招呼话术:')
        if ok and text:
            self.update_list_and_config(self.parent.listWidget_greet, self.greet_list, 'new_friend_msg', text)

    def delGreet(self):
        self.delete_items(self.parent.listWidget_greet, self.greet_list, 'new_friend_msg')

    def update_ui_from_data(self):
        self.parent.lineEdit_BaseURL.setText(self.data.get("base_url", ""))
        self.parent.lineEdit_Prompt.setText(self.data.get("prompt", ""))
        self.parent.lineEdit_room_admin.setText(self.data.get("admin", ""))
        self.parent.lineEdit_api_Token.setText(self.data.get("api_key", ""))
        self.parent.lineEdit_Model_1.setText(self.data.get("model1", ""))
        self.parent.lineEdit_room_welcome.setText(self.data.get("group_welcome_msg", ""))
        self.greet_list = self.data.get("new_friend_msg", [])
        self.parent.listWidget_greet.clear()
        for greet in self.greet_list:
            self.parent.listWidget_greet.addItem(greet)

    def save_config(self):
        self.data["base_url"] = self.parent.lineEdit_BaseURL.text()
        self.data["prompt"] = self.parent.lineEdit_Prompt.text()
        self.data["admin"] = self.parent.lineEdit_room_admin.text()
        self.data["api_key"] = self.parent.lineEdit_api_Token.text()
        self.data["model1"] = self.parent.lineEdit_Model_1.text()
        self.data["group_welcome_msg"] = self.parent.lineEdit_room_welcome.text()
        self.data["new_friend_msg"] = [self.parent.listWidget_greet.item(i).text() for i in range(self.parent.listWidget_greet.count())]
        try:
            for key in ["base_url", "prompt", "admin", "api_key", "model1", "group_welcome_msg", "new_friend_msg"]:
                update_config_value(key, self.data[key])
            QtWidgets.QMessageBox.information(self, "配置保存成功", "配置文件已成功更新，重启生效")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "配置保存出错", f"配置文件保存失败了: {str(e)}")

    def load_config(self):
        log("WARNING", "您点击了加载配置！")

    def update_list_and_config(self, list_widget, item_list, config_key, text):
        if text:
            item_list.append(text)
            list_widget.addItem(text)
            update_config_value(config_key, item_list)

    def delete_items(self, list_widget, item_list, config_key):
        selected_items = list_widget.selectedItems()
        for item in selected_items:
            row = list_widget.row(item)
            del item_list[row]
            list_widget.takeItem(row)
        update_config_value(config_key, item_list)

    def init_list_from_data(self, config_key, item_list, list_widget):
        item_list.clear()
        items = self.data.get(config_key, [])
        for item in items:
            item_list.append(item)
            list_widget.addItem(item)
