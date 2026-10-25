from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QProgressBar, QHeaderView, QMessageBox)

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
        self.task = None
        layout = QVBoxLayout(self)
        self.controls = QWidget()
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        instruction = QLabel("Выберите название в дереве, измените его и нажмите «Сохранить».")
        instruction.setWordWrap(True)
        controls_layout.addWidget(instruction)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Название", "Элементов"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        controls_layout.addWidget(self.tree, 1)
        self.selected_label = QLabel()
        self.selected_label.setWordWrap(True)
        self.selected_label.setTextFormat(Qt.PlainText)
        controls_layout.addWidget(self.selected_label)
        controls_layout.addWidget(QLabel("Название"))
        self.name = QLineEdit()
        controls_layout.addWidget(self.name)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        controls_layout.addWidget(self.hint)
        self.save_button = QPushButton("Сохранить")
        self.save_button.setMinimumHeight(44)
        self.save_button.clicked.connect(self.save_name)
        controls_layout.addWidget(self.save_button)
        self.delete_button = QPushButton("Удалить категорию…")
        self.delete_button.setMinimumHeight(44)
        self.delete_button.clicked.connect(self.delete_category)
        controls_layout.addWidget(self.delete_button)
        self.undo_button = QPushButton("Отменить последнее изменение")
        self.undo_button.setFlat(True)
        self.undo_button.clicked.connect(self.undo)
        controls_layout.addWidget(self.undo_button)
        layout.addWidget(self.controls, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.progress.hide()
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.name.textChanged.connect(self._name_changed)
        self.refresh()

    def selection(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def refresh(self, selected=None):
        selected = selected or self.selection()
        expanded = set()

        def remember(parent):
            for i in range(parent.childCount()):
                item = parent.child(i)
                value = item.data(0, Qt.UserRole)
                if value and item.isExpanded():
                    expanded.add((value["level"], value["source"], value["category"]))
                remember(item)

        remember(self.tree.invisibleRootItem())
        self.service.catalog = self.service.manager.catalog(self.service.project_id)
        catalog = self.service.catalog
        records = catalog.items()
        self.tree.blockSignals(True)
        self.tree.clear()
        category_root = QTreeWidgetItem(self.tree, ["Категории и подкатегории"])
        type_root = QTreeWidgetItem(self.tree, ["Типы кастомизации"])
        category_root.setExpanded(True)
        type_root.setExpanded(True)
        selected_item = None
        first_item = None

        def add(parent, level, source, category, count):
            nonlocal selected_item, first_item
            item = QTreeWidgetItem(parent, [source, str(count)])
            value = {"level": level, "source": source, "category": category}
            item.setData(0, Qt.UserRole, value)
            if first_item is None:
                first_item = item
            if value == selected:
                selected_item = item
            item.setExpanded((level, source, category) in expanded)
            return item

        for category in catalog.categories():
            rows = [r for r in records if r.get("category") == category]
            category_node = add(category_root, "category", category, "", len(rows))
            for sub in catalog.subcategories(category):
                add(category_node, "subcategory", sub, category,
                    sum(r.get("subcategory") == sub for r in rows))
        for kind in catalog.types():
            add(type_root, "type", kind, "", sum(r.get("type") == kind for r in records))
        self.tree.setCurrentItem(selected_item or first_item)
        if selected_item:
            parent = selected_item.parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree.scrollToItem(selected_item)
        self.tree.blockSignals(False)
        self._selection_changed()
        self.undo_button.setVisible(self.service.undo_info() is not None)

    def _selection_changed(self):
        value = self.selection()
        labels = {"category": "Категория", "subcategory": "Подкатегория", "type": "Тип кастомизации"}
        self.name.setEnabled(value is not None)
        self.delete_button.setVisible(bool(value and value["level"] == "category"))
        if value is None:
            self.selected_label.setText("Выберите категорию, подкатегорию или тип.")
            self.name.clear()
            self.hint.clear()
            return
        location = f'{value["category"]} → ' if value["level"] == "subcategory" else ""
        self.selected_label.setText(f'{labels[value["level"]]}: {location}{value["source"]}')
        self.name.setText(value["source"])
        count = self.tree.currentItem().text(1)
        suffix = " Также изменится ключ в выводе GUID." if value["level"] == "type" else ""
        self.hint.setText(f"Название изменится у элементов: {count}.{suffix}")
        self._name_changed()

    def _name_changed(self):
        value = self.selection()
        self.save_button.setEnabled(bool(value and self.name.text().strip()
            and self.name.text().strip() != value["source"]) and not self.is_saving)
        if not self.is_saving:
            self.message.clear()

    def save_name(self):
        if self.is_saving or not self.selection():
            return
        value = self.selection()
        try:
            plan = self.service.preview_rename(value["level"], value["source"], self.name.text(), value["category"])
        except (ValueError, OSError) as error:
            self.message.setText(str(error))
            return
        plan["selection"] = dict(value, source=self.name.text().strip())
        self._start(plan)

    def undo(self):
        if not self.is_saving:
            self._start(None)

    def _confirm_delete_category(self, source):
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle("Удаление категории")
        confirmation.setIcon(QMessageBox.Warning)
        confirmation.setTextFormat(Qt.PlainText)
        confirmation.setText(f'Удалить категорию «{source}»?')
        confirmation.setInformativeText("Категория пуста. Её пустые подкатегории также будут удалены. Изменение можно отменить.")
        delete = confirmation.addButton("Удалить", QMessageBox.DestructiveRole)
        cancel = confirmation.addButton("Отмена", QMessageBox.RejectRole)
        confirmation.setDefaultButton(cancel)
        confirmation.setEscapeButton(cancel)
        confirmation.exec()
        return confirmation.clickedButton() is delete

    def delete_category(self):
        value = self.selection()
        if self.is_saving or not value or value["level"] != "category":
            return
        try:
            plan = self.service.preview_delete_category(value["source"])
        except (ValueError, OSError) as error:
            self.message.setText(str(error))
            return
        if self._confirm_delete_category(value["source"]):
            self._start(plan)

    def _start(self, plan):
        self.is_saving = True
        self.busy_changed.emit(True)
        self.controls.setEnabled(False)
        self.progress.show()
        deleting = plan and plan.get("operation") == "delete_category"
        self.message.setText("Удаление категории…" if deleting else "Сохранение…" if plan else "Отмена изменения…")
        self.task = StructureTask(self.service, plan, self)
        self.task.finished.connect(self._finished)
        self.task.start()

    @Slot()
    def _finished(self):
        task = self.task
        self.task = None
        self.is_saving = False
        self.busy_changed.emit(False)
        self.progress.hide()
        self.controls.setEnabled(True)
        if task.error:
            self.message.setText(f"Не удалось применить изменение: {task.error}")
        else:
            self.refresh(task.plan.get("selection") if task.plan else None)
            deleting = task.plan and task.plan.get("operation") == "delete_category"
            self.message.setText("Категория удалена." if deleting else "Название сохранено." if task.plan else "Изменение отменено.")
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
        self.structure = StructurePanel(manager, project_id)
        self.structure.changed.connect(self.changed.emit)
        self.structure.busy_changed.connect(self._busy_changed)
        self.tabs.addTab(self.structure, "Каталог")
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.addWidget(QLabel("Название проекта"))
        self.name = QLineEdit(manager.get(project_id)["name"])
        general_layout.addWidget(self.name)
        self.message = QLabel()
        self.message.setWordWrap(True)
        general_layout.addWidget(self.message)
        save = QPushButton("Сохранить")
        save.setMinimumHeight(44)
        save.clicked.connect(self._save_name)
        general_layout.addWidget(save)
        general_layout.addStretch()
        self.tabs.addTab(general, "Проект")
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
        if not self.is_saving:
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
