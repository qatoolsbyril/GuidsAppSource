from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QListWidget, QListWidgetItem, QComboBox, QProgressBar)

from app.structure import StructureService


class StructureTask(QThread):
    def __init__(self, service, plan, parent):
        super().__init__(parent)
        self.service = service
        self.plan = plan
        self.error = None

    def run(self):
        try:
            if self.plan is None:
                self.service.undo()
            else:
                self.service.apply(self.plan)
        except Exception as error:
            self.error = str(error)


class StructurePanel(QWidget):
    changed = Signal()
    busy_changed = Signal(bool)

    def __init__(self, manager, project_id, parent=None):
        super().__init__(parent)
        self.service = StructureService(manager, project_id)
        self.is_saving = False
        self.pending = None
        self.task = None
        layout = QVBoxLayout(self)
        self.controls = QWidget()
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        category_page = QWidget()
        columns = QHBoxLayout(category_page)
        self.categories = QListWidget()
        self.subcategories = QListWidget()
        for title, widget in (("Категории", self.categories), ("Подкатегории", self.subcategories)):
            column = QVBoxLayout()
            column.addWidget(QLabel(title))
            column.addWidget(widget)
            columns.addLayout(column)
        self.tabs.addTab(category_page, "Категории и подкатегории")
        self.types = QListWidget()
        self.tabs.addTab(self.types, "Типы кастомизации")
        controls_layout.addWidget(self.tabs, 1)
        self.scope = QComboBox()
        self.scope.addItem("Категория", "category")
        self.scope.addItem("Подкатегория выбранной категории", "subcategory")
        self.scope.addItem("Тип кастомизации во всём проекте", "type")
        controls_layout.addWidget(self.scope)
        self.selected_label = QLabel()
        self.selected_label.setWordWrap(True)
        controls_layout.addWidget(self.selected_label)
        self.action = QComboBox()
        controls_layout.addWidget(self.action)
        self.target_label = QLabel("Новое название")
        self.target = QComboBox()
        self.target.setEditable(True)
        controls_layout.addWidget(self.target_label)
        controls_layout.addWidget(self.target)
        self.destination_label = QLabel("Категория назначения")
        self.destination = QComboBox()
        controls_layout.addWidget(self.destination_label)
        controls_layout.addWidget(self.destination)
        preview = QPushButton("Проверить изменение")
        preview.setMinimumHeight(44)
        preview.clicked.connect(self.preview_change)
        controls_layout.addWidget(preview)
        self.undo_button = QPushButton("Отменить последнее изменение структуры…")
        self.undo_button.setMinimumHeight(44)
        self.undo_button.clicked.connect(self.preview_undo)
        controls_layout.addWidget(self.undo_button)
        layout.addWidget(self.controls, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        layout.addWidget(self.message)
        self.confirmation = QWidget()
        confirmation_layout = QVBoxLayout(self.confirmation)
        confirmation_layout.setContentsMargins(0, 0, 0, 0)
        self.confirm = QPushButton("Подтвердить изменение")
        self.confirm.setMinimumHeight(44)
        self.confirm.clicked.connect(self.apply_pending)
        cancel = QPushButton("Отмена")
        cancel.setMinimumHeight(44)
        cancel.clicked.connect(self.cancel_preview)
        confirmation_layout.addWidget(self.confirm)
        confirmation_layout.addWidget(cancel)
        layout.addWidget(self.confirmation)
        self.confirmation.hide()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.progress.hide()
        self.categories.currentRowChanged.connect(self._category_selected)
        self.subcategories.currentRowChanged.connect(lambda: self._select_scope("subcategory"))
        self.types.currentRowChanged.connect(lambda: self._select_scope("type"))
        self.tabs.currentChanged.connect(lambda index: self._select_scope("type" if index else "category"))
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.action.currentIndexChanged.connect(self._action_changed)
        self.refresh()

    def _value(self, widget):
        item = widget.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def _fill(self, widget, names, counts):
        selected = self._value(widget)
        widget.blockSignals(True)
        widget.clear()
        for name in names:
            item = QListWidgetItem(f"{name}  ({counts.get(name, 0)})")
            item.setData(Qt.UserRole, name)
            widget.addItem(item)
        row = next((i for i in range(widget.count()) if widget.item(i).data(Qt.UserRole) == selected), 0)
        widget.setCurrentRow(row)
        widget.blockSignals(False)

    def refresh(self):
        self.service.catalog = self.service.manager.catalog(self.service.project_id)
        records = self.service.catalog.items()
        self._fill(self.categories, self.service.catalog.categories(),
                   {name: sum(r.get("category") == name for r in records) for name in self.service.catalog.categories()})
        self._fill(self.types, self.service.catalog.types(),
                   {name: sum(r.get("type") == name for r in records) for name in self.service.catalog.types()})
        self._fill_subcategories()
        self._scope_changed()
        self.undo_button.setEnabled(self.service.undo_info() is not None)

    def _fill_subcategories(self):
        category = self._value(self.categories)
        records = self.service.catalog.items()
        names = self.service.catalog.subcategories(category)
        self._fill(self.subcategories, names,
                   {name: sum(r.get("category") == category and r.get("subcategory") == name for r in records) for name in names})

    def _select_scope(self, level):
        self.scope.setCurrentIndex(self.scope.findData(level))
        self._scope_changed()

    def _category_selected(self):
        self._fill_subcategories()
        self._select_scope("category")

    def _source(self):
        return self._value({"category": self.categories, "subcategory": self.subcategories, "type": self.types}[self.scope.currentData()])

    def _scope_changed(self):
        if self.is_saving:
            return
        self.cancel_preview()
        self.selected_label.setText(f'Выбрано: {self._source() or "—"}')
        previous = self.action.currentData()
        self.action.blockSignals(True)
        self.action.clear()
        actions = [("Переименовать", "rename"), ("Объединить с существующим", "merge"),
                   ("Добавить новое название", "add"), ("Удалить пустое название", "remove")]
        if self.scope.currentData() == "subcategory":
            actions += [("Перенести в другую категорию", "move"), ("Убрать подраздел, сохранить элементы", "flatten")]
        for label, value in actions:
            self.action.addItem(label, value)
        index = self.action.findData(previous)
        self.action.setCurrentIndex(max(index, 0))
        self.action.blockSignals(False)
        self._action_changed()

    def _action_changed(self):
        self.cancel_preview()
        action = self.action.currentData()
        needs_target = action in {"rename", "merge", "add"}
        self.target_label.setVisible(needs_target)
        self.target.setVisible(needs_target)
        self.target_label.setText("Объединить с" if action == "merge" else "Новое название")
        self.target.clear()
        self.target.setEditable(action != "merge")
        level = self.scope.currentData()
        catalog = self.service.catalog
        names = catalog.categories() if level == "category" else catalog.types() if level == "type" else catalog.subcategories(self._value(self.categories))
        if action == "merge":
            self.target.addItems([n for n in names if n != self._source()])
        else:
            self.target.setCurrentText("")
        self.destination_label.setVisible(action == "move")
        self.destination.setVisible(action == "move")
        self.destination.clear()
        self.destination.addItems([n for n in catalog.categories() if n != self._value(self.categories)])

    def preview_change(self):
        try:
            plan = self.service.preview(self.scope.currentData(), self.action.currentData(),
                source=self._source(), target=self.target.currentText(),
                category=self._value(self.categories), destination=self.destination.currentText())
        except (ValueError, OSError) as error:
            self.message.setText(str(error))
            return
        self.pending = plan
        self.controls.setEnabled(False)
        self.message.setText(f'{plan["description"]}\nБудет изменено элементов: {plan["count"]}.\nПеред применением будет сохранена резервная копия.')
        self.confirmation.show()

    def preview_undo(self):
        try:
            state = self.service.undo_info()
            if state is None:
                raise ValueError("Нет изменения структуры для отмены.")
        except (ValueError, OSError) as error:
            self.message.setText(str(error))
            return
        self.pending = "undo"
        self.controls.setEnabled(False)
        self.message.setText(f'Отменить последнее изменение?\n{state["description"]}\nЭлементов: {state["count"]}. Отмена доступна, если каталог с тех пор не менялся.')
        self.confirmation.show()

    def cancel_preview(self):
        if self.is_saving:
            return
        self.pending = None
        self.controls.setEnabled(True)
        self.confirmation.hide()

    def apply_pending(self):
        if self.pending is None or self.is_saving:
            return
        self.is_saving = True
        self.busy_changed.emit(True)
        self.confirmation.hide()
        self.progress.show()
        self.message.setText("Изменение структуры…")
        self.task = StructureTask(self.service, None if self.pending == "undo" else self.pending, self)
        self.task.finished.connect(self._finished)
        self.task.start()

    @Slot()
    def _finished(self):
        task = self.task
        self.task = None
        self.is_saving = False
        self.busy_changed.emit(False)
        self.progress.hide()
        self.cancel_preview()
        if task.error:
            self.message.setText(f"Не удалось применить изменение: {task.error}")
        else:
            self.refresh()
            self.message.setText("Структура обновлена.")
            self.changed.emit()
        task.deleteLater()


class ProjectSettingsPanel(QWidget):
    changed = Signal()
    cancelled = Signal()

    def __init__(self, manager, project_id, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.project_id = project_id
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Настройки проекта"))
        self.tabs = QTabWidget()
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.addWidget(QLabel("Название проекта"))
        self.name = QLineEdit(manager.get(project_id)["name"])
        general_layout.addWidget(self.name)
        self.message = QLabel()
        self.message.setWordWrap(True)
        general_layout.addWidget(self.message)
        save = QPushButton("Сохранить название проекта")
        save.setMinimumHeight(44)
        save.clicked.connect(self._save_name)
        general_layout.addWidget(save)
        general_layout.addStretch()
        self.tabs.addTab(general, "Проект")
        self.structure = StructurePanel(manager, project_id)
        self.structure.changed.connect(self.changed.emit)
        self.structure.busy_changed.connect(self._busy_changed)
        self.tabs.addTab(self.structure, "Структура каталога")
        layout.addWidget(self.tabs, 1)
        self.back = QPushButton("Назад к GUID")
        self.back.setMinimumHeight(44)
        self.back.clicked.connect(self.go_back)
        layout.addWidget(self.back)

    @property
    def is_saving(self):
        return self.structure.is_saving

    def _busy_changed(self, busy):
        self.tabs.tabBar().setEnabled(not busy)
        self.back.setEnabled(not busy)

    def go_back(self):
        if self.is_saving:
            return
        if self.structure.pending is not None:
            self.structure.cancel_preview()
        else:
            self.cancelled.emit()

    def _save_name(self):
        try:
            current = self.manager.get(self.project_id)
            self.manager.save_project(self.name.text(), current["categories"], current["types"], self.project_id)
        except (ValueError, OSError) as error:
            self.message.setText(str(error))
            return
        self.changed.emit()
        self.message.setText("Название проекта сохранено.")
