from pathlib import Path
from PySide6.QtCore import Qt, Signal, QThread, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QFileDialog, QComboBox, QFrame, QStackedWidget, QScrollArea, QProgressBar, QMessageBox)


class CatalogWriteTask(QThread):
    """Only filesystem work runs here; widgets stay on the GUI thread."""

    def __init__(self, catalog, record, main_icon, sub_icon, original, parent, operation="save"):
        super().__init__(parent)
        self.catalog = catalog
        self.record = record
        self.main_icon = main_icon
        self.sub_icon = sub_icon
        self.original = dict(original) if original else None
        self.result = None
        self.error = None
        self.operation = operation

    def run(self):
        try:
            if self.operation == "delete":
                self.result = self.catalog.delete_item(self.record["guid"])
            else:
                self.result = self.catalog.save_item(self.record, self.main_icon, self.sub_icon, self.original)
        except Exception as error:
            self.error = str(error)


class DropImageLabel(QLabel):
    def __init__(self, on_image_selected, parent=None):
        super().__init__(parent)
        self._on_image_selected = on_image_selected
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumSize(140, 140)
        self.setMaximumHeight(180)
        self.setFrameShape(QFrame.StyledPanel)
        self.clear_image()

    def dragEnterEvent(self, event):
        if any(u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
               for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and self.set_image(Path(url.toLocalFile())):
                self._on_image_selected(Path(url.toLocalFile()))
                event.acceptProposedAction()
                break

    def set_image(self, path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return False
        self.setPixmap(pixmap.scaled(160, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        return True

    def clear_image(self):
        self.setPixmap(QPixmap())
        self.setText("Перетащите изображение сюда")


class AddCustomizationWindow(QWidget):
    saved = Signal(object)
    deleted = Signal(object)
    cancelled = Signal()

    def __init__(self, catalog, record=None, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.record = dict(record) if record else None
        self.selected_main_icon = self.selected_sub_icon = None
        self.is_saving = False
        self._save_task = None
        self.pages = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.pages)
        self.busy_label = QLabel("Сохранение…")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        outer.addWidget(self.busy_label)
        outer.addWidget(self.progress)
        self.busy_label.hide()
        self.progress.hide()
        form = QWidget()
        layout = QVBoxLayout(form)
        title = QLabel("Редактирование элемента" if record else "Добавление элемента")
        title.setStyleSheet("font-size: 18px; font-weight: bold")
        layout.addWidget(title)
        self.input_name = QLineEdit()
        self.input_guid = QLineEdit()
        self.input_guid.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        self.input_guid.setReadOnly(bool(record))
        self.combo_category = QComboBox()
        self.combo_category.setEditable(True)
        self.combo_category.addItems(catalog.categories())
        self.combo_subcat = QComboBox()
        self.combo_subcat.setEditable(True)
        self.combo_type = QComboBox()
        self.combo_type.setEditable(True)
        self.combo_type.addItems(catalog.types())
        for label, field in (("Название", self.input_name), ("GUID", self.input_guid),
                             ("Категория", self.combo_category), ("Подкатегория", self.combo_subcat),
                             ("Тип кастомизации", self.combo_type)):
            layout.addWidget(QLabel(label))
            layout.addWidget(field)
        self.combo_category.currentTextChanged.connect(self._category_changed)
        self._category_changed(self.combo_category.currentText())
        images = QHBoxLayout()
        self.preview_main = DropImageLabel(self._select_main)
        self.preview_sub = DropImageLabel(self._select_sub)
        for label, preview, kind in (("Иконка элемента", self.preview_main, "main"),
                                     ("Иконка подкатегории", self.preview_sub, "sub")):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(preview)
            button = QPushButton("Выбрать файл…")
            button.clicked.connect(lambda checked=False, k=kind: self._pick_icon(k))
            column.addWidget(button)
            images.addLayout(column)
        layout.addLayout(images)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QVBoxLayout()
        buttons.setSpacing(8)
        save = QPushButton("Сохранить")
        save.clicked.connect(self._save)
        cancel = QPushButton("Назад к GUID")
        cancel.clicked.connect(self.cancelled.emit)
        for button in (save, cancel):
            button.setMinimumHeight(44)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        if self.record:
            delete = QPushButton("Удалить элемент…")
            delete.setMinimumHeight(44)
            delete.clicked.connect(self._delete)
            buttons.addWidget(delete)
        layout.addLayout(buttons)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form)
        self.pages.addWidget(scroll)
        if record:
            self.input_name.setText(record.get("name", ""))
            self.input_guid.setText(record.get("guid", ""))
            self.combo_category.setCurrentText(record.get("category", ""))
            self.combo_subcat.setCurrentText(record.get("subcategory") or "")
            self.combo_type.setCurrentText(record.get("type", ""))
            icon = catalog.icon(record)
            if icon:
                self.preview_main.set_image(icon)
            folder = catalog.icons_dir / record.get("category", "") / (record.get("subcategory") or "")
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                if (folder / f"icon{ext}").is_file():
                    self.preview_sub.set_image(folder / f"icon{ext}")
                    break

    def _category_changed(self, category):
        self.combo_subcat.clear()
        self.combo_subcat.addItems(self.catalog.subcategories(category))
        self.combo_subcat.setCurrentText("")

    def _select_main(self, path):
        self.selected_main_icon = path

    def _select_sub(self, path):
        self.selected_sub_icon = path

    def _pick_icon(self, kind):
        picker = QFileDialog(self, Qt.Widget)
        picker.setOption(QFileDialog.DontUseNativeDialog, True)
        picker.setWindowFlags(Qt.Widget)
        picker.setFileMode(QFileDialog.ExistingFile)
        picker.setNameFilter("Изображения (*.png *.jpg *.jpeg *.webp)")
        picker.setDirectory(str(self.catalog.root))
        self.pages.addWidget(picker)
        self.pages.setCurrentWidget(picker)

        def finish(accepted):
            if accepted and picker.selectedFiles():
                path = Path(picker.selectedFiles()[0])
                preview = self.preview_main if kind == "main" else self.preview_sub
                if preview.set_image(path):
                    (self._select_main if kind == "main" else self._select_sub)(path)
                else:
                    self.message.setText("Не удалось открыть изображение.")
            self.pages.setCurrentIndex(0)
            self.pages.removeWidget(picker)
            picker.deleteLater()

        picker.accepted.connect(lambda: finish(True))
        picker.rejected.connect(lambda: finish(False))

    def _save(self):
        if self.is_saving:
            return
        record = dict(self.record or {})
        record.update(name=self.input_name.text().strip(), guid=self.input_guid.text().strip(),
                      category=self.combo_category.currentText().strip(),
                      subcategory=self.combo_subcat.currentText().strip() or None,
                      type=self.combo_type.currentText().strip())
        self._start_write(record)

    def _confirm_delete(self):
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle("Удаление элемента")
        confirmation.setIcon(QMessageBox.Warning)
        confirmation.setTextFormat(Qt.PlainText)
        confirmation.setText(f'Удалить элемент «{self.record["name"]}»?')
        confirmation.setInformativeText(f'GUID: {self.record["guid"]}\nЭлемент будет удалён из каталога текущего проекта.')
        delete = confirmation.addButton("Удалить", QMessageBox.DestructiveRole)
        cancel = confirmation.addButton("Отмена", QMessageBox.RejectRole)
        confirmation.setDefaultButton(cancel)
        confirmation.setEscapeButton(cancel)
        confirmation.exec()
        return confirmation.clickedButton() is delete

    def _delete(self):
        if self.is_saving or not self.record:
            return
        if self._confirm_delete():
            self._start_write(dict(self.record), operation="delete")

    def _start_write(self, record, operation="save"):
        self.is_saving = True
        self.busy_label.setText("Удаление…" if operation == "delete" else "Сохранение…")
        self.pages.setEnabled(False)
        self.message.clear()
        self.busy_label.show()
        self.progress.show()
        self._save_task = CatalogWriteTask(self.catalog, record, self.selected_main_icon,
                                           self.selected_sub_icon, self.record, self, operation)
        self._save_task.finished.connect(self._save_finished)
        self._save_task.start()

    @Slot()
    def _save_finished(self):
        task = self._save_task
        self._save_task = None
        self.is_saving = False
        self.pages.setEnabled(True)
        self.busy_label.hide()
        self.progress.hide()
        task.deleteLater()
        if task.error is not None:
            action = "удалить" if task.operation == "delete" else "сохранить"
            self.message.setText(f"Не удалось {action}: {task.error}")
            return
        if task.operation == "delete":
            self.deleted.emit(task.result)
            return
        if not self.record:
            self.input_name.clear()
            self.input_guid.clear()
            self.selected_main_icon = self.selected_sub_icon = None
            self.preview_main.clear_image()
            self.preview_sub.clear_image()
        self.message.setText("Элемент сохранён.")
        self.saved.emit(task.result)
