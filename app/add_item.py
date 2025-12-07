# app/add_item.py
import os
import sys
import json
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QMimeData
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QMessageBox, QFrame
)

# ---------- КОНФИГУРАЦИЯ ----------
DEFAULT_CATEGORIES = ["arrows", "offers", "battle_pass", "events", "maps"]
DEFAULT_TYPES = ["arrows","bow", "hat", "body", "beard", "emojis", "glasses", "phrases", "stickers"]

def get_project_root() -> Path:
    # Ищем корень проекта (директорию, содержащую папку app)
    env = os.getenv("GUIDS_APP_ROOT")
    if env:
        p = Path(env).resolve()
        if (p / "app").is_dir():
            return p
    here = Path(__file__).resolve()
    for p in [here.parent] + list(here.parents):
        if (p / "app").is_dir():
            return p
    # если упаковано в PyInstaller
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "app").is_dir():
            return exe_dir
    return Path.cwd().resolve()

PROJECT_ROOT = get_project_root()
DATA_DIR = PROJECT_ROOT / "data"
ASSETS_DIR = PROJECT_ROOT / "assets" / "icons"
ALL_INDEX = DATA_DIR / "_all.json"

# ---------- УТИЛИТЫ ----------
def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if not ALL_INDEX.exists():
        ALL_INDEX.write_text("[]", encoding="utf-8")

def load_json(path: Path):
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def list_categories():
    # Собираем категории из файлов в data + дефолтные
    existing = set(DEFAULT_CATEGORIES)
    if DATA_DIR.exists():
        for p in DATA_DIR.glob("*.json"):
            if p.name == "_all.json":
                continue
            existing.add(p.stem)
    return sorted(existing)

def list_subcategories(category: str):
    if not category:
        return []
    cat_file = DATA_DIR / f"{category}.json"
    if not cat_file.exists():
        return []
    data = load_json(cat_file)
    subs = set()
    for rec in data:
        s = rec.get("subcategory")
        if s:
            subs.add(s)
    return sorted(subs)

def is_guid_unique(candidate: str) -> bool:
    if not candidate:
        return True
    all_list = load_json(ALL_INDEX)
    for rec in all_list:
        if str(rec.get("guid", "")).lower() == candidate.lower():
            return False
    return True

# ---------- DROP IMAGE WIDGET ----------
class DropImageLabel(QLabel):
    def __init__(self, on_image_selected, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(220, 220)
        self.setFrameShape(QFrame.StyledPanel)
        self.setText("Перетащи иконку сюда\nили нажми «Выбрать файл»")
        self._on_image_selected = on_image_selected
        self._current_path: Path | None = None


    def dragEnterEvent(self, event: QDragEnterEvent):
        mime: QMimeData = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            local = Path(url.toLocalFile())
            if local.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                self.set_image(local)
                try:
                    self._on_image_selected(local)
                except Exception:
                    pass
                break

    def set_image(self, path: Path):
        self._current_path = path
        pix = QPixmap(str(path))
        if not pix.isNull():
            self.setPixmap(pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.setText("Не удалось открыть изображение")

    def clear_image(self):
        self._current_path = None
        self.setPixmap(QPixmap())
        self.setText("Перетащи иконку сюда\nили нажми «Выбрать файл»")

# ---------- AddCustomizationWindow ----------
class AddCustomizationWindow(QWidget):
    """
    Окно добавления кастомизации.
    Поведение:
      - При создании устанавливается self.on_saved_callback = None (внешнее окно назначает его при открытии)
      - После сохранения вызывает on_saved_callback() если установлен
      - Сохраняет последние выбранные category/subcategory/type в класс-переменных
      - Кнопка Очистить очищает полностью (если нужно) или частично
    """
    last_category: str = ""
    last_subcategory: str = ""
    last_type: str = ""

    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.on_saved_callback = None  # <- внешний код может назначить callback

        self.setWindowTitle("Добавление кастомизации")
        self.setMinimumWidth(600)

        # выбранные файлы иконок
        self.selected_main_icon: Path | None = None
        self.selected_sub_icon: Path | None = None

        # --- UI поля ---
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("Название элемента (обязательно)")

        self.input_guid = QLineEdit()
        self.input_guid.setPlaceholderText("GUID (обязательно, формат UUID)")

        self.combo_category = QComboBox()
        self.combo_category.setEditable(True)
        self.combo_category.addItems(list_categories())
        self.combo_category.currentTextChanged.connect(self._category_changed)

        self.combo_subcat = QComboBox()
        self.combo_subcat.setEditable(True)

        self.combo_type = QComboBox()
        self.combo_type.setEditable(False)
        self.combo_type.addItems(["<Не указано>"] + DEFAULT_TYPES)

        # Иконки (drop)
        self.preview_main = DropImageLabel(self._on_main_icon_selected)
        btn_main_icon = QPushButton("Выбрать иконку элемента…")
        btn_main_icon.clicked.connect(self._pick_main_icon)

        self.preview_sub = DropImageLabel(self._on_sub_icon_selected)
        btn_sub_icon = QPushButton("Выбрать иконку подкатегории…")
        btn_sub_icon.clicked.connect(self._pick_sub_icon)

        # Действия
        btn_save = QPushButton("Сохранить")
        btn_save.clicked.connect(self._save)

        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(self._clear_form_full)

        # Сборка layout
        left = QVBoxLayout()
        left.addWidget(QLabel("Название"))
        left.addWidget(self.input_name)
        left.addSpacing(6)
        left.addWidget(QLabel("GUID"))
        left.addWidget(self.input_guid)
        left.addSpacing(6)
        left.addWidget(QLabel("Категория"))
        left.addWidget(self.combo_category)
        left.addSpacing(6)
        left.addWidget(QLabel("Подкатегория"))
        left.addWidget(self.combo_subcat)
        left.addSpacing(6)
        left.addWidget(QLabel("Тип кастомизации"))
        left.addWidget(self.combo_type)
        left.addSpacing(12)
        row_actions = QHBoxLayout()
        row_actions.addWidget(btn_save)
        row_actions.addWidget(btn_clear)
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

        # Восстанавливаем последние выбранные значения (если есть)
        self._restore_last_values()
        self.adjustSize()
        self.setFixedSize(self.size())

    # ---------- вспомогательные ----------
    def _restore_last_values(self):
        self._restoring = True  # <-- добавили
        try:
            if AddCustomizationWindow.last_category:
                self.combo_category.setEditText(AddCustomizationWindow.last_category)
                self._category_changed(AddCustomizationWindow.last_category)

            if AddCustomizationWindow.last_subcategory:
                self.combo_subcat.setEditText(AddCustomizationWindow.last_subcategory)

            if AddCustomizationWindow.last_type:
                idx = self.combo_type.findText(AddCustomizationWindow.last_type)
                if idx >= 0:
                    self.combo_type.setCurrentIndex(idx)
        finally:
            self._restoring = False  # <-- снимаем флаг

    def _category_changed(self, cat_name: str):
        # если мы ВРУЧНУЮ меняем категорию → подкатегорию сбрасываем
        # но если мы восстанавливаем значения (restore), то подкатегория НЕ сбросится
        restoring = getattr(self, "_restoring", False)

        current_sub = self.combo_subcat.currentText().strip()

        self.combo_subcat.blockSignals(True)
        self.combo_subcat.clear()

        subcats = list_subcategories(cat_name)
        self.combo_subcat.addItems(subcats)

        if restoring and current_sub:
            # при восстановлении подставляем прежнюю подкатегорию
            self.combo_subcat.setEditText(current_sub)
        else:
            # при ручной смене категории сбрасываем
            self.combo_subcat.setEditText("")

        self.combo_subcat.blockSignals(False)

    def _update_subcat_items(self, category: str):
        self.combo_subcat.clear()
        if category:
            subs = list_subcategories(category)
            self.combo_subcat.addItems(subs)
        # оставляем текст в editable, если пользователь уже ввёл что-то
        # ничего дополнительно не трогаем

    # ---------- работа с иконками ----------
    def _pick_main_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать иконку элемента", str(PROJECT_ROOT),
                                              "Изображения (*.png *.jpg *.jpeg *.webp)")
        if path:
            p = Path(path)
            self.preview_main.set_image(p)
            self._on_main_icon_selected(p)

    def _pick_sub_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать иконку подкатегории", str(PROJECT_ROOT),
                                              "Изображения (*.png *.jpg *.jpeg *.webp)")
        if path:
            p = Path(path)
            self.preview_sub.set_image(p)
            self._on_sub_icon_selected(p)

    def _on_main_icon_selected(self, path: Path):
        self.selected_main_icon = path

    def _on_sub_icon_selected(self, path: Path):
        self.selected_sub_icon = path

    # ---------- GUID валидация ----------
    def _get_valid_guid(self) -> str | None:
        txt = self.input_guid.text().strip()
        if not txt:
            # требуем GUID по дизайну — пользователь должен ввести UUID
            QMessageBox.warning(self, "Ошибка", "GUID обязателен. Введите значение (UUID).")
            return None
        try:
            g = str(uuid.UUID(txt))
        except Exception:
            QMessageBox.warning(self, "Ошибка", "GUID имеет неверный формат.")
            return None
        if not is_guid_unique(g):
            QMessageBox.warning(self, "Ошибка", "Такой GUID уже существует.")
            return None
        return g

    # ---------- сохранение ----------
    def _save(self):
        name = self.input_name.text().strip()
        category = self.combo_category.currentText().strip()
        subcat = self.combo_subcat.currentText().strip() or None
        ctype = self.combo_type.currentText().strip()
        if ctype == "<Не указано>":
            ctype = ""

        if not name:
            return self._err("Заполни название.")
        if not category:
            return self._err("Укажи категорию.")
        if not ctype:
            return self._err("Выбери тип кастомизации.")
        if not self.selected_main_icon:
            return self._err("Добавь иконку элемента.")

        guid = self._get_valid_guid()
        if not guid:
            return

        # Сохраняем последние выбранные значения (для последующего добавления)
        AddCustomizationWindow.last_category = category
        AddCustomizationWindow.last_subcategory = subcat or ""
        AddCustomizationWindow.last_type = ctype

        # Папки для иконок
        cat_dir = ASSETS_DIR / category
        if subcat:
            cat_dir = cat_dir / subcat
        cat_dir.mkdir(parents=True, exist_ok=True)

        # Копируем основную иконку
        main_ext = self.selected_main_icon.suffix.lower()
        main_dst = cat_dir / f"{guid}{main_ext}"
        shutil.copy2(self.selected_main_icon, main_dst)

        # Копируем иконку подкатегории если указана и пользователь выбрал файл для подкатегории
        if self.selected_sub_icon and subcat:
            sub_ext = self.selected_sub_icon.suffix.lower()
            sub_dst = cat_dir / f"icon{sub_ext}"
            shutil.copy2(self.selected_sub_icon, sub_dst)

        now = datetime.now(timezone.utc).isoformat()
        record = {
            "guid": guid,
            "name": name,
            "category": category,
            "subcategory": subcat,
            "type": ctype,
            "icon_path": str(main_dst.relative_to(PROJECT_ROOT).as_posix()),
            "created_at": now,
        }

        # Сохраняем в файл категории
        cat_file = DATA_DIR / f"{category}.json"
        cat_list = load_json(cat_file)
        cat_list.append(record)
        save_json(cat_file, cat_list)

        # Сохраняем в общий индекс
        all_list = load_json(ALL_INDEX)
        all_list.append(record)
        save_json(ALL_INDEX, all_list)

        # Обновляем список подкатегорий (чтобы новая появилась сразу)
        self._update_subcat_items(category)

        QMessageBox.information(self, "Готово", f"Элемент сохранён ✅\nGUID: {guid}")

        # Вызов callback у внешнего окна (например, GuidSearchWindow) для обновления дерева
        try:
            if self.on_saved_callback:
                self.on_saved_callback()
        except Exception:
            pass

        # После сохранения очищаем всё кроме категории/subcategory/type
        self._clear_after_save()

    # ---------- очистка формы ----------
    def _clear_after_save(self):
        # Очищаем название, GUID и иконки, но оставляем категорию/подкатегорию/тип
        self.input_name.clear()
        self.input_guid.clear()

        self.preview_main.clear_image()
        self.preview_sub.clear_image()

        self.selected_main_icon = None
        self.selected_sub_icon = None

    def _clear_form_full(self):
        # Полное очищение — полностью сбрасываем все поля, включая категорию/подкатегорию/тип
        self.input_name.clear()
        self.input_guid.clear()
        self.combo_category.setCurrentIndex(0) if self.combo_category.count() > 0 else self.combo_category.setEditText("")
        self.combo_subcat.clear()
        self.combo_type.setCurrentIndex(0)

        self.preview_main.clear_image()
        self.preview_sub.clear_image()

        self.selected_main_icon = None
        self.selected_sub_icon = None

        # сбрасываем последние сохранённые значения
        AddCustomizationWindow.last_category = ""
        AddCustomizationWindow.last_subcategory = ""
        AddCustomizationWindow.last_type = ""

    # ---------- ошибки ----------
    def _err(self, msg: str):
        QMessageBox.warning(self, "Ошибка", msg)

# ---------- standalone launch ----------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = AddCustomizationWindow()
    w.show()
    sys.exit(app.exec())
