# app/GuidSearchWindow.py
from pathlib import Path

import json
import os
import glob
import sys
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import (
    QWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPlainTextEdit, QPushButton, QApplication, QMessageBox
)
from app.add_item import DATA_DIR, ASSETS_DIR, ALL_INDEX, AddCustomizationWindow, ensure_dirs, load_json, PROJECT_ROOT, list_categories, list_subcategories
from app.edit_item import EditCustomizationWindow


def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)







# Примеры
config_file = resource_path("data/config.json")
add_item_file = resource_path("app/add_item.py")
icon_file = resource_path("assets/icons/my_icon.ico")

class GuidSearchWindow(QWidget):
    def __init__(self):
        super().__init__()
        ensure_dirs()

        self.setWindowTitle("Поиск GUID")
        self.setMinimumSize(1000, 600)

        self.add_window = None
        self.selected_guids: dict[str, str] = {}

        # Поиск
        self.search_line = QLineEdit()
        self.search_line.setPlaceholderText("Поиск по имени или GUID...")
        self.search_line.textChanged.connect(self._filter_tree)

        # Дерево
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(64, 64))
        self.tree.itemDoubleClicked.connect(self._add_guid_to_right)

        self._init_fonts()

        # Правая панель
        self.guid_output = QPlainTextEdit()
        self.guid_output.setReadOnly(True)
        self.guid_output.setPlaceholderText("Выбранные GUID...")

        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(self._clear_selected)

        btn_add = QPushButton("Добавить элемент")
        btn_add.clicked.connect(self._open_add_window)

        btn_edit = QPushButton("Редактировать элемент")
        btn_edit.clicked.connect(self._edit_selected_element)

        # Layout
        layout_main = QVBoxLayout()
        layout_main.addWidget(self.search_line)

        layout_split = QHBoxLayout()
        layout_split.addWidget(self.tree, 1)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.guid_output)
        right_layout.addWidget(btn_clear)
        right_layout.addWidget(btn_add)
        right_layout.addWidget(btn_edit)
        layout_split.addLayout(right_layout, 1)

        layout_main.addLayout(layout_split)
        self.setLayout(layout_main)

        self._load_items_into_tree()
        # Все JSON файлы в папке data
        json_files = glob.glob(resource_path("data/*.json"))
        for file_path in json_files:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # работаем с data

        # Все иконки
        icon_folder = resource_path("assets/icons")
        for root, dirs, files in os.walk(icon_folder):
            for file in files:
                if file.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    icon_path = os.path.join(root, file)
                    # работаем с icon_path, например QIcon(icon_path)

    # ------------------------------ #
    # Шрифты
    # ------------------------------ #
    def _init_fonts(self):
        self.tree_font_category = QFont()
        self.tree_font_category.setPointSize(12)
        self.tree_font_category.setBold(True)

        self.tree_font_subcategory = QFont()
        self.tree_font_subcategory.setPointSize(11)
        self.tree_font_type = QFont()
        self.tree_font_type.setPointSize(11)
        self.tree_font_element = QFont()
        self.tree_font_element.setPointSize(10)

    # ------------------------------ #
    # Загрузка элементов
    # ------------------------------ #
    def _load_items_into_tree(self):
        self.tree.clear()
        all_items = load_json(ALL_INDEX)

        # Сортировка по структуре: category -> subcategory -> type -> [elements]
        cat_map = {}
        type_map_all = {}
        for rec in all_items:
            cat = rec.get("category") or "Unknown"
            sub = rec.get("subcategory") or "<No Subcategory>"
            ctype = rec.get("type") or "unknown"
            cat_map.setdefault(cat, {}).setdefault(sub, {}).setdefault(ctype, []).append(rec)
            type_map_all.setdefault(ctype, []).append(rec)

        # ------------------ ALL -------------------
        all_item = QTreeWidgetItem(self.tree)
        all_item.setText(0, "All")
        all_item.setFont(0, self.tree_font_category)
        all_item.setData(0, Qt.UserRole, {"type": "all"})

        for ctype, elements in type_map_all.items():
            type_item = QTreeWidgetItem(all_item)
            type_item.setText(0, ctype)
            type_item.setFont(0, self.tree_font_type)
            type_item.setData(0, Qt.UserRole, {"type": "type_group"})
            for rec in elements:
                self._create_element_item(type_item, rec)

        # ------------------ CATEGORIES -------------------
        for cat_name, sub_dict in cat_map.items():
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, cat_name)
            cat_item.setFont(0, self.tree_font_category)
            cat_item.setData(0, Qt.UserRole, {"type": "category"})

            for sub_name, type_dict in sub_dict.items():
                sub_item = QTreeWidgetItem(cat_item)
                sub_item.setText(0, sub_name)
                sub_item.setFont(0, self.tree_font_subcategory)
                sub_item.setData(0, Qt.UserRole, {"type": "subcategory"})

                # Иконка подкатегории
                sub_icon_path = None
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    candidate = ASSETS_DIR / cat_name / sub_name / f"icon{ext}"
                    if candidate.exists():
                        sub_icon_path = candidate
                        break
                if sub_icon_path:
                    sub_item.setIcon(0, QIcon(str(sub_icon_path)))

                for ctype_name, elements in type_dict.items():
                    type_item = QTreeWidgetItem(sub_item)
                    type_item.setText(0, ctype_name)
                    type_item.setFont(0, self.tree_font_type)
                    type_item.setData(0, Qt.UserRole, {"type": "type_group"})
                    for rec in elements:
                        self._create_element_item(type_item, rec)

        # self.tree.expandAll()

    def _create_element_item(self, parent, rec):
        el = QTreeWidgetItem(parent)
        el.setText(0, rec.get("name") or "")
        el.setFont(0, self.tree_font_element)

        icon_path = Path(PROJECT_ROOT) / rec.get("icon_path")
        if icon_path.exists():
            el.setIcon(0, QIcon(str(icon_path)))

        el.setData(0, Qt.UserRole, {
            "type": "element",
            "guid": rec.get("guid"),
            "custom_type": rec.get("type", "unknown")
        })

    # ------------------------------ #
    # Фильтр
    # ------------------------------ #
    def _filter_tree(self, text: str):
        text = text.lower()
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            self._filter_recursive(root.child(i), text)

    def _filter_recursive(self, item, text):
        visible = False
        for i in range(item.childCount()):
            if self._filter_recursive(item.child(i), text):
                visible = True
        data = item.data(0, Qt.UserRole)
        if data and data.get("type") == "element":
            name = item.text(0).lower()
            guid = data.get("guid", "").lower()
            if text in name or text in guid:
                visible = True
        item.setHidden(not visible)
        return visible

    # ------------------------------ #
    # Выбор элемента
    # ------------------------------ #
    def _add_guid_to_right(self, item, _column):
        data = item.data(0, Qt.UserRole)
        if not data or data.get("type") != "element":
            return
        guid = data.get("guid")
        if not guid:
            return
        ctype = (data.get("custom_type") or "").strip() or "unknown"
        if guid not in self.selected_guids:
            self.selected_guids[guid] = ctype
            self._update_guid_output()

    def _update_guid_output(self):
        type_map = {}
        for guid, ctype in self.selected_guids.items():
            type_map.setdefault(ctype, []).append(guid)
        result_lines = []
        for ctype in sorted(type_map.keys()):
            guids = type_map[ctype]
            if len(guids) == 1:
                result_lines.append(f'"{ctype}": "{guids[0]}"')
            else:
                inside = ",\n  ".join(f'"{g}"' for g in sorted(guids))
                result_lines.append(f'"{ctype}": [\n  {inside}\n]')
        self.guid_output.setPlainText(",\n".join(result_lines))

    # ------------------------------ #
    # Кнопки
    # ------------------------------ #
    def _clear_selected(self):
        self.selected_guids.clear()
        self.guid_output.clear()

    def _open_add_window(self):
        if self.add_window is None or not self.add_window.isVisible():
            self.add_window = AddCustomizationWindow()
            self.add_window.on_saved_callback = self._load_items_into_tree
            self.add_window.show()
        else:
            self.add_window.raise_()
            self.add_window.activateWindow()

    def _edit_selected_element(self):
        selected = self.tree.currentItem()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите элемент для редактирования")
            return
        data = selected.data(0, Qt.UserRole)
        if not data or data.get("type") != "element":
            QMessageBox.warning(self, "Ошибка", "Выберите именно элемент")
            return
        guid = data.get("guid")
        all_items = load_json(ALL_INDEX)
        record = next((r for r in all_items if r.get("guid") == guid), None)
        if record:
            EditCustomizationWindow(record, on_saved_callback=self._load_items_into_tree).show()

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = GuidSearchWindow()
    window.show()
    sys.exit(app.exec())
