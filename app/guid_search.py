import json
from PySide6.QtCore import Qt, QSize, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QIcon, QShortcut, QKeySequence
from PySide6.QtWidgets import (QWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QLabel,
    QComboBox, QStackedWidget, QSplitter, QScrollArea, QFrame, QStyledItemDelegate, QFileDialog)
from app.storage import ProjectManager
from app.add_item import AddCustomizationWindow
from app.edit_item import EditCustomizationWindow


class CustomizationItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        record = index.data(Qt.UserRole)
        if record and record.get("type") == "arrows" and not option.icon.isNull():
            option.decorationSize = option.icon.actualSize(QSize(112, 56))


class GuidSearchWindow(QWidget):
    def __init__(self, manager=None):
        super().__init__()
        interface_font = self.font()
        interface_font.setPointSizeF(max(interface_font.pointSizeF(), 9) + 1)
        self.setFont(interface_font)
        self.manager = manager or ProjectManager()
        self.catalog = self.manager.catalog()
        self.selected_guids = {}
        self.editor = None
        self._catalog_status = ""
        self.setWindowTitle("Каталог кастомизации — поиск GUID")
        self.resize(1200, 780)
        self.setMinimumSize(960, 640)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("Проект"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(220)
        header.addWidget(self.project_combo, 1)
        self.new_button = QPushButton("Новый проект")
        self.settings_button = QPushButton("Настройки проекта")
        self.new_button.clicked.connect(lambda: self._open_project_form(False))
        self.settings_button.clicked.connect(lambda: self._open_project_form(True))
        header.addWidget(self.new_button)
        header.addWidget(self.settings_button)
        layout.addLayout(header)
        self.search_line = QLineEdit()
        self.search_line.setPlaceholderText("Поиск по названию или GUID в выбранном проекте…")
        self.search_line.textChanged.connect(self._filter_tree)
        layout.addWidget(self.search_line)
        self.tree = QTreeWidget()
        catalog_font = self.font()
        catalog_font.setPointSizeF(interface_font.pointSizeF() + 2)
        self.tree.setFont(catalog_font)
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(56, 56))
        self.tree.setItemDelegate(CustomizationItemDelegate(self.tree))
        self.tree.itemDoubleClicked.connect(self._add_guid_to_right)
        self.pages = QStackedWidget()
        output_page = QWidget()
        output_layout = QVBoxLayout(output_page)
        output_layout.addWidget(QLabel("Выбранные GUID · двойной щелчок по элементу"))
        self.guid_output = QPlainTextEdit()
        self.guid_output.setReadOnly(True)
        self.guid_output.setPlaceholderText("Выберите элементы в каталоге слева")
        output_layout.addWidget(self.guid_output)
        clear = QPushButton("Очистить")
        clear.clicked.connect(self._clear_selected)
        output_layout.addWidget(clear)
        add = QPushButton("Добавить элемент")
        add.clicked.connect(self._open_add_window)
        edit = QPushButton("Редактировать выбранный элемент")
        edit.clicked.connect(self._edit_selected_element)
        for button in (clear, add, edit):
            button.setMinimumHeight(44)
        output_layout.addWidget(add)
        output_layout.addWidget(edit)
        self.pages.addWidget(output_page)
        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(self.pages)
        splitter.setSizes([600, 600])
        splitter.setChildrenCollapsible(False)
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(splitter)
        layout.addWidget(self.body, 1)
        self.drawer = QFrame(self.body)
        self.drawer.setFrameShape(QFrame.StyledPanel)
        self.drawer.setAutoFillBackground(True)
        self.drawer_layout = QVBoxLayout(self.drawer)
        self.drawer_layout.setContentsMargins(0, 0, 0, 0)
        self.drawer.hide()
        self._drawer_progress = 0.0
        self.drawer_animation = QVariantAnimation(self)
        self.drawer_animation.setDuration(240)
        self.drawer_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.drawer_animation.valueChanged.connect(self._position_drawer)
        self.drawer_animation.finished.connect(self._drawer_finished)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._refresh_projects()
        self.project_combo.currentIndexChanged.connect(self._change_project)
        self._load_items_into_tree()
        self.back_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.back_shortcut.activated.connect(self._go_back)

    def _go_back(self):
        if self.editor is None or getattr(self.editor, "is_saving", False):
            return
        if isinstance(self.editor, AddCustomizationWindow):
            picker = self.editor.pages.currentWidget()
            if isinstance(picker, QFileDialog):
                picker.reject()
                return
        self._close_editor()

    def _refresh_projects(self):
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for project in self.manager.projects:
            self.project_combo.addItem(project["name"], project["id"])
        self.project_combo.setCurrentIndex(self.project_combo.findData(self.catalog.project["id"]))
        self.project_combo.blockSignals(False)

    def _change_project(self, index):
        project_id = self.project_combo.itemData(index)
        if not project_id:
            return
        try:
            catalog = self.manager.catalog(project_id)
            catalog.items()
            self.manager.select(project_id)
        except (ValueError, OSError) as error:
            self.status.setText(f"Не удалось открыть проект: {error}")
            self._refresh_projects()
            return
        self.catalog = catalog
        self._clear_selected()
        self.search_line.clear()
        self._close_editor()
        self._load_items_into_tree()

    def _set_editor(self, widget):
        if getattr(self.editor, "is_saving", False):
            widget.deleteLater()
            return
        self.drawer_animation.stop()
        self._clear_drawer_content()
        self.editor = widget
        self.drawer_layout.addWidget(widget)
        self.drawer.setEnabled(True)
        self.drawer.show()
        self.drawer.raise_()
        self._animate_drawer(1.0)
        # Keep an unfinished form bound to its project until Save or Back.
        for control in (self.project_combo, self.new_button, self.settings_button):
            control.setEnabled(False)

    def _close_editor(self):
        if getattr(self.editor, "is_saving", False):
            return
        if self.editor:
            self.editor = None
            self.drawer.setEnabled(False)
            self._animate_drawer(0.0)
        for control in (self.project_combo, self.new_button, self.settings_button):
            control.setEnabled(True)
        self.status.setText(self._catalog_status)

    def closeEvent(self, event):
        if getattr(self.editor, "is_saving", False):
            self.status.setText("Дождитесь завершения операции перед закрытием приложения.")
            event.ignore()
            return
        super().closeEvent(event)

    def _clear_drawer_content(self):
        while self.drawer_layout.count():
            widget = self.drawer_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()

    def _animate_drawer(self, target):
        self.drawer_animation.stop()
        self.drawer_animation.setStartValue(self._drawer_progress)
        self.drawer_animation.setEndValue(target)
        self.drawer_animation.start()

    def _position_drawer(self, progress):
        self._drawer_progress = float(progress)
        width = self.body.width() // 2
        self.drawer.setGeometry(self.body.width() - round(width * self._drawer_progress),
                                0, width, self.body.height())

    def _drawer_finished(self):
        if self.editor is None:
            self.drawer.hide()
            self._clear_drawer_content()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "drawer"):
            self._position_drawer(self._drawer_progress)

    def _open_project_form(self, editing):
        project = self.catalog.project if editing else None
        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.addWidget(QLabel("Настройки проекта" if editing else "Новый локальный проект"))
        name = QLineEdit(project["name"] if project else "")
        categories = QPlainTextEdit("\n".join(project["categories"]) if project else "")
        types = QPlainTextEdit("\n".join(project["types"]) if project else "")
        for label, field in (("Название проекта", name), ("Категории — по одной на строку", categories),
                             ("Типы кастомизации — по одному на строку", types)):
            form_layout.addWidget(QLabel(label))
            form_layout.addWidget(field)
        form_layout.addWidget(QLabel("Новые категории и типы можно вводить при добавлении элемента."))
        message = QLabel()
        message.setWordWrap(True)
        form_layout.addWidget(message)
        save = QPushButton("Сохранить проект" if editing else "Создать проект")
        back = QPushButton("Назад к GUID")
        back.clicked.connect(self._close_editor)
        for button in (save, back):
            button.setMinimumHeight(44)
        form_layout.addWidget(save)
        form_layout.addWidget(back)

        def commit():
            try:
                result = self.manager.save_project(name.text(), categories.toPlainText().splitlines(),
                    types.toPlainText().splitlines(), project["id"] if project else None)
            except (ValueError, OSError) as error:
                message.setText(str(error))
                return
            self.catalog = self.manager.catalog(result["id"])
            self._refresh_projects()
            self._clear_selected()
            self.search_line.clear()
            self._close_editor()
            self._load_items_into_tree()

        save.clicked.connect(commit)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form)
        self._set_editor(scroll)

    def _load_items_into_tree(self):
        self.tree.clear()
        try:
            records = self.catalog.items()
        except (ValueError, OSError) as error:
            self._catalog_status = f"Не удалось прочитать каталог: {error}"
            self.status.setText(self._catalog_status)
            return
        self.selected_guids = {r["guid"]: r.get("type", "unknown") for r in records if r.get("guid") in self.selected_guids}
        self._update_guid_output()
        self._item_count = len(records)
        self._all_node = QTreeWidgetItem(self.tree, ["Все элементы"])
        for rec in records:
            self._insert_record(rec)
        self._filter_tree(self.search_line.text())
        self._update_catalog_status()

    def _update_catalog_status(self):
        self._catalog_status = (f'{self.catalog.project["name"]} · Элементов: {self._item_count}' if self._item_count
                                else "Проект пуст. Добавьте первый элемент.")
        self.status.setText(self._catalog_status)

    def _insert_record(self, rec, refresh_sub_icon=False):
        def group(parent, name, level):
            for i in range(parent.childCount()):
                child = parent.child(i)
                if (child is not self._all_node and child.text(0) == name
                        and child.data(0, Qt.UserRole + 1) == level):
                    return child
            node = QTreeWidgetItem(parent, [name])
            node.setData(0, Qt.UserRole + 1, level)
            return node

        category = rec.get("category") or "Без категории"
        subcategory = (rec.get("subcategory") or "").strip()
        kind = rec.get("type") or "unknown"
        category_node = group(self.tree.invisibleRootItem(), category, "category")
        sub_node = group(category_node, subcategory, "subcategory") if subcategory else category_node
        folder = self.catalog.icons_dir / category / (rec.get("subcategory") or "")
        if subcategory and (refresh_sub_icon or sub_node.icon(0).isNull()):
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                if (folder / f"icon{ext}").is_file():
                    sub_node.setIcon(0, QIcon(str(folder / f"icon{ext}")))
                    break
        icon_path = self.catalog.icon(rec)
        icon = QIcon(str(icon_path)) if icon_path else QIcon()
        for parent in (group(self._all_node, kind, "type"), group(sub_node, kind, "type")):
            node = QTreeWidgetItem(parent, [rec.get("name") or "Без названия"])
            node.setData(0, Qt.UserRole, rec)
            node.setToolTip(0, rec.get("guid", ""))
            node.setIcon(0, icon)

    def _remove_record_nodes(self, guid):
        removed = False

        def remove_matches(parent):
            nonlocal removed
            for i in range(parent.childCount() - 1, -1, -1):
                node = parent.child(i)
                old_record = node.data(0, Qt.UserRole)
                if old_record:
                    if old_record.get("guid") == guid:
                        parent.takeChild(i)
                        removed = True
                else:
                    remove_matches(node)
                    if not node.childCount() and node is not self._all_node:
                        parent.takeChild(i)

        remove_matches(self.tree.invisibleRootItem())
        return removed

    def _refresh_saved_item(self, record):
        """Replace the two appearances of one item without reloading the catalog."""
        self.tree.setUpdatesEnabled(False)
        try:
            removed = self._remove_record_nodes(record["guid"])
            self._insert_record(record, refresh_sub_icon=True)
            if not removed:
                self._item_count += 1
            if record["guid"] in self.selected_guids:
                self.selected_guids[record["guid"]] = record.get("type") or "unknown"
                self._update_guid_output()
            self._filter_tree(self.search_line.text())
            self._update_catalog_status()
        finally:
            self.tree.setUpdatesEnabled(True)

    def _remove_deleted_item(self, record):
        self.tree.setUpdatesEnabled(False)
        try:
            if self._remove_record_nodes(record["guid"]):
                self._item_count -= 1
            self.selected_guids.pop(record["guid"], None)
            self._update_guid_output()
            self._filter_tree(self.search_line.text())
            self._update_catalog_status()
        finally:
            self.tree.setUpdatesEnabled(True)

    def _filter_tree(self, text):
        def visit(node):
            record = node.data(0, Qt.UserRole)
            if record:
                visible = text.casefold() in node.text(0).casefold() or text.casefold() in record.get("guid", "").casefold()
            else:
                children = [visit(node.child(i)) for i in range(node.childCount())]
                visible = any(children) or not text
                if text:
                    node.setExpanded(visible)
            node.setHidden(not visible)
            return visible
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def _add_guid_to_right(self, item, column):
        record = item.data(0, Qt.UserRole)
        if record and record.get("guid"):
            self.selected_guids[record["guid"]] = record.get("type") or "unknown"
            self._update_guid_output()
            if self.editor:
                self.status.setText("GUID добавлен. Список доступен по кнопке «Назад к GUID».")
            else:
                self.status.setText(self._catalog_status)

    def _update_guid_output(self):
        groups = {}
        for guid, kind in self.selected_guids.items():
            groups.setdefault(kind, []).append(guid)
        sections = []
        for kind, values in sorted(groups.items()):
            value = json.dumps(values[0] if len(values) == 1 else sorted(values),
                               ensure_ascii=False, indent=2)
            indented_value = "\n".join("    " + line for line in value.splitlines())
            sections.append(f'{json.dumps(kind, ensure_ascii=False)}:\n{indented_value}')
        self.guid_output.setPlainText(",\n".join(sections))

    def _clear_selected(self):
        self.selected_guids.clear()
        self.guid_output.clear()

    def _open_add_window(self):
        form = AddCustomizationWindow(self.catalog)
        form.cancelled.connect(self._close_editor)
        form.saved.connect(self._refresh_saved_item)
        self._set_editor(form)

    def _edit_selected_element(self):
        node = self.tree.currentItem()
        record = node.data(0, Qt.UserRole) if node else None
        if not record:
            self.status.setText("Выберите элемент в каталоге для редактирования.")
            return
        form = EditCustomizationWindow(self.catalog, record)
        form.cancelled.connect(self._close_editor)
        form.saved.connect(self._refresh_saved_item)
        form.saved.connect(self._close_editor)
        form.deleted.connect(self._remove_deleted_item)
        form.deleted.connect(self._close_editor)
        self._set_editor(form)
