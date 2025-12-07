import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QComboBox, QPushButton, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox
)
from app.add_item import ASSETS_DIR, PROJECT_ROOT, DATA_DIR, DEFAULT_TYPES, DropImageLabel, load_json, save_json, list_categories, list_subcategories

ALL_INDEX = DATA_DIR / "_all.json"

class EditCustomizationWindow(QWidget):
    _instance = None  # Класс для блокировки нескольких окон

    def __init__(self, record: dict, on_saved_callback=None):
        if EditCustomizationWindow._instance:
            # Уже есть открытое окно
            EditCustomizationWindow._instance.raise_()
            EditCustomizationWindow._instance.activateWindow()
            self.close()
            return
        super().__init__()
        EditCustomizationWindow._instance = self

        self.record = record
        self.on_saved_callback = on_saved_callback
        self.selected_main_icon: Path | None = None
        self.selected_sub_icon: Path | None = None

        self.setWindowTitle(f"Редактирование: {record.get('name')}")
        self.setMinimumWidth(600)

        # Поля
        self.input_name = QLineEdit(record.get("name", ""))
        self.input_name.setPlaceholderText("Название элемента (обязательно)")

        self.input_guid = QLineEdit(record.get("guid", ""))
        self.input_guid.setReadOnly(True)

        # Категория
        self.combo_category = QComboBox()
        self.combo_category.setEditable(True)
        self.combo_category.addItems(list_categories())
        self.combo_category.setCurrentText(record.get("category", ""))
        self.combo_category.currentTextChanged.connect(self._category_changed)

        # Подкатегория
        self.combo_subcat = QComboBox()
        self.combo_subcat.setEditable(True)
        self._update_subcategories(record.get("category"))
        self.combo_subcat.setCurrentText(record.get("subcategory") or "")

        # Тип кастомизации
        self.combo_type = QComboBox()
        self.combo_type.setEditable(False)
        self.combo_type.addItems(["<Не указано>"] + DEFAULT_TYPES)
        self.combo_type.setCurrentText(record.get("type") or "<Не указано>")

        # Основная иконка
        self.preview_main = DropImageLabel(self._on_main_icon_selected)
        main_icon_path = PROJECT_ROOT / record.get("icon_path")
        if main_icon_path.exists():
            self.preview_main.set_image(main_icon_path)
        btn_main_icon = QPushButton("Выбрать иконку элемента…")
        btn_main_icon.clicked.connect(self._pick_main_icon)

        # Подкатегория
        self.preview_sub = DropImageLabel(self._on_sub_icon_selected)
        sub_icon_path = None
        cat = record.get("category")
        sub = record.get("subcategory")
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = ASSETS_DIR / cat / (sub or "") / f"icon{ext}"
            if candidate.exists():
                sub_icon_path = candidate
                break
        if sub_icon_path:
            self.preview_sub.set_image(sub_icon_path)
        btn_sub_icon = QPushButton("Выбрать иконку подкатегории…")
        btn_sub_icon.clicked.connect(self._pick_sub_icon)

        # Кнопки
        btn_save = QPushButton("Сохранить")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.close)

        # Layout
        left = QVBoxLayout()
        left.addWidget(QLabel("Название"))
        left.addWidget(self.input_name)
        left.addSpacing(8)
        left.addWidget(QLabel("GUID"))
        left.addWidget(self.input_guid)
        left.addSpacing(8)
        left.addWidget(QLabel("Категория"))
        left.addWidget(self.combo_category)
        left.addSpacing(8)
        left.addWidget(QLabel("Подкатегория"))
        left.addWidget(self.combo_subcat)
        left.addSpacing(8)
        left.addWidget(QLabel("Тип кастомизации"))
        left.addWidget(self.combo_type)
        left.addSpacing(12)
        row_actions = QHBoxLayout()
        row_actions.addWidget(btn_save)
        row_actions.addWidget(btn_cancel)
        left.addLayout(row_actions)
        left.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Иконка элемента"))
        right.addWidget(self.preview_main)
        right.addWidget(btn_main_icon)
        right.addSpacing(12)
        right.addWidget(QLabel("Иконка подкатегории"))
        right.addWidget(self.preview_sub)
        right.addWidget(btn_sub_icon)
        right.addStretch(1)

        root = QHBoxLayout()
        root.addLayout(left, 1)
        root.addLayout(right, 1)
        self.setLayout(root)
        self.adjustSize()
        self.setFixedSize(self.size())

    # ----- Подкатегории по выбранной категории -----
    def _category_changed(self, cat_name):
        self._update_subcategories(cat_name)

    def _update_subcategories(self, category):
        self.combo_subcat.clear()
        self.combo_subcat.addItems(list_subcategories(category))
        self.combo_subcat.setEditText("")

    # ----- Работа с файлами -----
    def _pick_main_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать иконку элемента", str(PROJECT_ROOT),
            "Изображения (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            p = Path(path)
            self.preview_main.set_image(p)
            self._on_main_icon_selected(p)

    def _pick_sub_icon(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать иконку подкатегории", str(PROJECT_ROOT),
            "Изображения (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            p = Path(path)
            self.preview_sub.set_image(p)
            self._on_sub_icon_selected(p)

    def _on_main_icon_selected(self, path: Path):
        self.selected_main_icon = path

    def _on_sub_icon_selected(self, path: Path):
        self.selected_sub_icon = path

    # ----- Сохранение -----
    def _save(self):
        name = self.input_name.text().strip()
        category = self.combo_category.currentText().strip()
        subcat = self.combo_subcat.currentText().strip() or None
        ctype = self.combo_type.currentText().strip()
        if ctype == "<Не указано>" or not ctype:
            return self._err("Выберите тип кастомизации")
        if not name:
            return self._err("Название обязательно")
        if not category:
            return self._err("Категория обязательна")

        guid = self.record.get("guid")
        cat_dir = ASSETS_DIR / category
        if subcat:
            cat_dir = cat_dir / subcat
        cat_dir.mkdir(parents=True, exist_ok=True)

        if self.selected_main_icon:
            main_ext = self.selected_main_icon.suffix.lower()
            main_dst = cat_dir / f"{guid}{main_ext}"
            shutil.copy2(self.selected_main_icon, main_dst)
            icon_path = str(main_dst.relative_to(PROJECT_ROOT).as_posix())
        else:
            icon_path = self.record.get("icon_path")

        if self.selected_sub_icon and subcat:
            sub_ext = self.selected_sub_icon.suffix.lower()
            sub_dst = cat_dir / f"icon{sub_ext}"
            shutil.copy2(self.selected_sub_icon, sub_dst)

        # Обновляем запись
        self.record.update({
            "name": name,
            "category": category,
            "subcategory": subcat,
            "type": ctype,
            "icon_path": icon_path,
        })

        # Файл категории
        cat_file = DATA_DIR / f"{category}.json"
        cat_list = load_json(cat_file)
        updated = False
        for i, rec in enumerate(cat_list):
            if rec.get("guid") == guid:
                cat_list[i] = self.record
                updated = True
                break
        if not updated:
            cat_list.append(self.record)
        save_json(cat_file, cat_list)

        # Общий индекс
        all_list = load_json(ALL_INDEX)
        for i, rec in enumerate(all_list):
            if rec.get("guid") == guid:
                all_list[i] = self.record
                break
        save_json(ALL_INDEX, all_list)

        QMessageBox.information(self, "Готово", "Элемент обновлён ✅")
        if self.on_saved_callback:
            self.on_saved_callback()
        self.close()

    def closeEvent(self, event):
        EditCustomizationWindow._instance = None
        event.accept()

    def _err(self, msg: str):
        QMessageBox.warning(self, "Ошибка", msg)
