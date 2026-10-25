import json
import os
import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QPlainTextEdit, QPushButton
from app.storage import ProjectManager, read_json, write_json
from app.guid_search import GuidSearchWindow

GUID = "188d669f-7af7-424f-a64f-f498ba8af486"


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = ProjectManager(self.root)
        self.image = self.root / "sample.png"
        image = QImage(32, 32, QImage.Format_ARGB32)
        image.fill(Qt.blue)
        image.save(str(self.image))

    def record(self, **changes):
        record = dict(guid=GUID, name="Hat", category="offers", subcategory=None, type="hat")
        record.update(changes)
        return record

    def window(self):
        window = GuidSearchWindow(self.manager)
        self.addCleanup(window.close)
        return window

    def wait_for_save(self, form):
        for _ in range(500):
            if not form.is_saving:
                return
            QTest.qWait(10)
        self.fail("Saving did not finish")

    def test_legacy_data_stays_in_place(self):
        record = self.record(icon_path="sample.png")
        write_json(self.root / "data/_all.json", [record])
        original = (self.root / "data/_all.json").read_bytes()
        window = self.window()
        self.assertEqual(window.catalog.items(), [record])
        self.assertEqual(window.catalog.icon(record), self.image)
        self.assertEqual((self.root / "data/_all.json").read_bytes(), original)
        self.assertFalse(self.manager.path.exists())

    def test_project_isolation_and_persistence(self):
        default = self.manager.catalog()
        default.save_item(self.record(), self.image)
        project = self.manager.save_project("Другая игра", ["skins"], ["vehicle"])
        other = self.manager.catalog()
        self.assertEqual(other.items(), [])
        other.save_item(self.record(category="skins", type="vehicle"), self.image)
        self.assertEqual(default.items()[0]["type"], "hat")
        self.assertEqual(other.items()[0]["type"], "vehicle")
        self.assertEqual(ProjectManager(self.root).catalog().project["id"], project["id"])
        self.assertNotEqual(default.icon(default.items()[0]), other.icon(other.items()[0]))

    def test_edit_moves_category_and_preserves_icon(self):
        catalog = self.manager.catalog()
        original = catalog.save_item(self.record(), self.image)
        updated = catalog.save_item(dict(original, category="events", type="custom"), original=original)
        self.assertEqual(read_json(catalog.data_dir / "offers.json", None), [])
        self.assertEqual(read_json(catalog.data_dir / "events.json", None), [updated])
        self.assertEqual(catalog.icon(updated), catalog.icon(original))
        self.assertIn("custom", catalog.types())
        self.assertEqual(len(catalog.items()), 1)

    def test_invalid_and_duplicate_input_does_not_change_index(self):
        catalog = self.manager.catalog()
        catalog.save_item(self.record(), self.image)
        original = catalog.index.read_bytes()
        with self.assertRaises(ValueError):
            catalog.save_item(self.record(), self.image)
        for changes in ({"guid": "bad"}, {"category": "../outside"},
                        {"category": "_all"}, {"subcategory": "CON"}, {"name": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                candidate = self.record(guid="288d669f-7af7-424f-a64f-f498ba8af486")
                candidate.update(changes)
                catalog.save_item(candidate, self.image)
        self.assertEqual(catalog.index.read_bytes(), original)

    def test_malformed_json_is_not_silently_overwritten(self):
        catalog = self.manager.catalog()
        catalog.index.parent.mkdir()
        catalog.index.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            catalog.save_item(self.record(), self.image)
        self.assertEqual(catalog.index.read_text(), "{broken")

    def test_failed_project_save_keeps_configuration(self):
        before = json.dumps(self.manager.config)
        with patch("app.storage.write_json", side_effect=PermissionError("read only")):
            with self.assertRaises(PermissionError):
                self.manager.save_project("New", [], ["hat"])
        self.assertEqual(json.dumps(self.manager.config), before)

    def test_embedded_add_edit_picker_and_search(self):
        window = self.window()
        window.show()
        window._open_add_window()
        form = window.editor
        self.assertFalse(form.isWindow())
        self.assertFalse(window.project_combo.isEnabled())
        form._pick_icon("main")
        picker = form.pages.currentWidget()
        self.assertIsInstance(picker, QFileDialog)
        self.assertFalse(picker.isWindow())
        picker.selectFile(str(self.image))
        picker.accept()
        self.assertEqual(form.selected_main_icon, self.image)
        form.input_name.setText("Hat")
        form.input_guid.setText(GUID)
        form.combo_category.setCurrentText("offers")
        form.combo_type.setCurrentText("new_type")
        form._save()
        self.wait_for_save(form)
        self.assertEqual(len(window.catalog.items()), 1)
        window._close_editor()
        node = window.tree.topLevelItem(0).child(0).child(0)
        window._add_guid_to_right(node, 0)
        self.assertIn(GUID, window.guid_output.toPlainText())
        window.search_line.setText("no match")
        self.assertTrue(node.isHidden())
        window.search_line.setText(GUID.upper())
        self.assertFalse(node.isHidden())
        window.tree.setCurrentItem(node)
        window._edit_selected_element()
        self.assertFalse(window.editor.isWindow())
        self.assertTrue(window.editor.input_guid.isReadOnly())
        window.editor.combo_type.setCurrentText("updated")
        form = window.editor
        form._save()
        self.wait_for_save(form)
        self.assertIsNone(window.editor)
        self.assertIn('"updated"', window.guid_output.toPlainText())

    def test_saving_keeps_ui_responsive_and_prevents_duplicate_saves(self):
        window = self.window()
        window.show()
        window._open_add_window()
        QTest.qWait(300)
        form = window.editor
        form.input_name.setText("Hat")
        form.input_guid.setText(GUID)
        form._select_main(self.image)
        release = threading.Event()
        actual_save = form.catalog.save_item

        def slow_save(*args):
            release.wait(3)
            return actual_save(*args)

        ticks = []
        with patch.object(form.catalog, "save_item", side_effect=slow_save) as save:
            try:
                form._save()
                form._save()
                QTimer.singleShot(10, lambda: ticks.append(True))
                QTest.qWait(60)
                self.assertTrue(ticks)
                self.assertTrue(form.progress.isVisible())
                self.assertFalse(form.pages.isEnabled())
                self.assertEqual(save.call_count, 1)
                window._close_editor()
                self.assertIs(window.editor, form)
                QTest.keyClick(window, Qt.Key_Escape)
                self.assertIs(window.editor, form)
                window.close()
                self.assertTrue(window.isVisible())
            finally:
                release.set()
                self.wait_for_save(form)
        self.assertTrue(form.pages.isEnabled())
        self.assertTrue(form.progress.isHidden())
        self.assertEqual(len(window.catalog.items()), 1)
        self.assertEqual(window._item_count, 1)
        self.assertIn("Элемент сохранён", form.message.text())

    def test_save_failure_preserves_form_and_allows_retry(self):
        window = self.window()
        window._open_add_window()
        form = window.editor
        form.input_name.setText("Hat")
        form.input_guid.setText(GUID)
        form._select_main(self.image)
        with patch.object(form.catalog, "save_item", side_effect=OSError("disk unavailable")):
            form._save()
            self.wait_for_save(form)
        self.assertIn("disk unavailable", form.message.text())
        self.assertEqual(form.input_name.text(), "Hat")
        self.assertTrue(form.pages.isEnabled())
        self.assertTrue(form.progress.isHidden())
        with patch.object(window, "_load_items_into_tree", side_effect=AssertionError("full reload")):
            form._save()
            self.wait_for_save(form)
        self.assertEqual(window._item_count, 1)

    def test_optional_subcategory_is_skipped_and_group_names_do_not_merge(self):
        catalog = self.manager.catalog()
        original = catalog.save_item(self.record(), self.image)
        other_guid = "288d669f-7af7-424f-a64f-f498ba8af486"
        catalog.save_item(self.record(guid=other_guid, subcategory="hat"), self.image)
        window = self.window()
        category = next(window.tree.topLevelItem(i) for i in range(window.tree.topLevelItemCount())
                        if window.tree.topLevelItem(i).text(0) == "offers")
        self.assertEqual(category.childCount(), 2)
        nodes = {category.child(i).data(0, Qt.UserRole + 1): category.child(i) for i in range(2)}
        self.assertEqual(nodes["type"].child(0).data(0, Qt.UserRole)["guid"], GUID)
        self.assertEqual(nodes["subcategory"].child(0).child(0).data(0, Qt.UserRole)["guid"], other_guid)
        updated = catalog.save_item(dict(original, subcategory="season"), original=original)
        window._refresh_saved_item(updated)
        self.assertEqual({category.child(i).text(0) for i in range(category.childCount())}, {"hat", "season"})

    def test_escape_returns_from_forms_and_image_picker(self):
        self.manager.catalog().save_item(self.record(), self.image)
        window = self.window()
        window.show()
        window.activateWindow()
        QTest.qWait(50)
        window._open_add_window()
        QTest.qWait(300)
        form = window.editor
        form._pick_icon("main")
        QTest.qWait(30)
        picker = form.pages.currentWidget()
        QTest.keyClick(picker, Qt.Key_Escape)
        self.assertIs(window.editor, form)
        self.assertEqual(form.pages.currentIndex(), 0)
        form.input_name.setFocus()
        QTest.keyClick(form.input_name, Qt.Key_Escape)
        self.assertIsNone(window.editor)
        QTest.qWait(300)
        for open_form in (lambda: window._open_project_form(False),
                          lambda: window._open_project_form(True),
                          window._edit_selected_element):
            window.tree.setCurrentItem(window._all_node.child(0).child(0))
            open_form()
            QTest.qWait(300)
            QTest.keyClick(window, Qt.Key_Escape)
            self.assertIsNone(window.editor)
            QTest.qWait(300)
        QTest.keyClick(window, Qt.Key_Escape)
        self.assertTrue(window.isVisible())

    def test_guid_hint_clears_when_returning_from_editor(self):
        self.manager.catalog().save_item(self.record(), self.image)
        window = self.window()
        catalog_status = window.status.text()
        node = window.tree.topLevelItem(0).child(0).child(0)
        window._open_add_window()
        window._add_guid_to_right(node, 0)
        self.assertIn("Назад к GUID", window.status.text())
        window.editor.cancelled.emit()
        self.assertEqual(window.status.text(), catalog_status)
        self.assertIn(GUID, window.guid_output.toPlainText())
        window._add_guid_to_right(node, 0)
        self.assertEqual(window.status.text(), catalog_status)

    def test_delete_requires_confirmation_and_removes_selected_item(self):
        catalog = self.manager.catalog()
        original = catalog.save_item(self.record(), self.image)
        self.manager.save_project("Other", [], ["hat"])
        other = self.manager.catalog()
        other.save_item(self.record(), self.image)
        self.manager.select("default")
        window = self.window()
        node = window._all_node.child(0).child(0)
        window._add_guid_to_right(node, 0)
        window.tree.setCurrentItem(node)
        window._edit_selected_element()
        form = window.editor
        self.assertTrue(any(b.text() == "Удалить элемент…" for b in form.findChildren(QPushButton)))
        with patch.object(form, "_confirm_delete", return_value=False) as confirm:
            form._delete()
            confirm.assert_called_once()
        self.assertFalse(form.is_saving)
        self.assertEqual(len(catalog.items()), 1)
        with patch.object(form, "_confirm_delete", return_value=True):
            form._delete()
            self.wait_for_save(form)
        self.assertEqual(catalog.items(), [])
        self.assertEqual(read_json(catalog.data_dir / "offers.json", None), [])
        self.assertEqual(window._all_node.childCount(), 0)
        self.assertEqual(window._item_count, 0)
        self.assertEqual(window.guid_output.toPlainText(), "")
        self.assertIsNone(window.editor)
        self.assertEqual(len(other.items()), 1)
        self.assertTrue(catalog.icon(original).is_file())

    def test_failed_delete_keeps_editor_and_record(self):
        catalog = self.manager.catalog()
        catalog.save_item(self.record(), self.image)
        window = self.window()
        window.tree.setCurrentItem(window._all_node.child(0).child(0))
        window._edit_selected_element()
        form = window.editor
        with patch.object(form, "_confirm_delete", return_value=True), patch.object(
                form.catalog, "delete_item", side_effect=OSError("read only")):
            form._delete()
            self.wait_for_save(form)
        self.assertIs(window.editor, form)
        self.assertEqual(len(catalog.items()), 1)
        self.assertIn("read only", form.message.text())
        self.assertTrue(form.pages.isEnabled())

    def test_delete_index_failure_restores_category(self):
        catalog = self.manager.catalog()
        record = catalog.save_item(self.record(), self.image)
        actual_write = write_json

        def fail_index(path, value):
            if path == catalog.index:
                raise OSError("index unavailable")
            actual_write(path, value)

        with patch("app.storage.write_json", side_effect=fail_index):
            with self.assertRaises(OSError):
                catalog.delete_item(GUID)
        self.assertEqual(catalog.items(), [record])
        self.assertEqual(read_json(catalog.data_dir / "offers.json", None), [record])

    def test_edit_refresh_preserves_other_nodes_and_removes_old_groups(self):
        catalog = self.manager.catalog()
        original = catalog.save_item(self.record(), self.image)
        other_guid = "288d669f-7af7-424f-a64f-f498ba8af486"
        catalog.save_item(self.record(guid=other_guid, category="events"), self.image)
        window = self.window()
        all_type = window._all_node.child(0)
        other_node = all_type.child(1)
        all_type.setExpanded(True)
        updated = catalog.save_item(dict(original, category="new", subcategory="season", type="body"), original=original)
        window.selected_guids[GUID] = "hat"
        window._refresh_saved_item(updated)
        self.assertIs(all_type.child(0), other_node)
        self.assertTrue(all_type.isExpanded())
        self.assertEqual(window._item_count, 2)
        self.assertEqual(window.selected_guids[GUID], "body")
        self.assertEqual({window.tree.topLevelItem(i).text(0) for i in range(window.tree.topLevelItemCount())},
                         {"Все элементы", "events", "new"})

    def test_forms_slide_over_right_half_without_resizing_window(self):
        self.manager.catalog().save_item(self.record(), self.image)
        window = self.window()
        window.show()
        self.app.processEvents()
        original_size = window.size()
        tree_geometry = window.tree.geometry()
        for open_form in (window._open_add_window,
                          lambda: window._open_project_form(False),
                          lambda: window._open_project_form(True),
                          window._edit_selected_element):
            window.tree.setCurrentItem(window.tree.topLevelItem(0).child(0).child(0))
            open_form()
            self.assertFalse(window.drawer.isWindow())
            self.assertLess(window._drawer_progress, 1.0)
            QTest.qWait(300)
            self.assertEqual(window._drawer_progress, 1.0)
            self.assertEqual(window.drawer.width(), window.body.width() // 2)
            self.assertEqual(window.drawer.geometry().right(), window.body.width() - 1)
            self.assertEqual(window.size(), original_size)
            self.assertEqual(window.tree.geometry(), tree_geometry)
            self.assertTrue(window.editor.isVisible())
            window._close_editor()
            QTest.qWait(300)
            self.assertFalse(window.drawer.isVisible())
            self.assertEqual(window.drawer_layout.count(), 0)
        window._open_add_window()
        QTest.qWait(300)
        window.resize(1100, 720)
        self.app.processEvents()
        self.assertEqual(window.drawer.width(), window.body.width() // 2)
        self.assertEqual(window.drawer.geometry().right(), window.body.width() - 1)

    def test_create_project_in_panel_and_switch_clears_selection(self):
        window = self.window()
        window.selected_guids[GUID] = "hat"
        window._open_project_form(False)
        form = window.editor.widget()
        form.findChild(QLineEdit).setText("Игра 2")
        fields = form.findChildren(QPlainTextEdit)
        fields[0].setPlainText("Skins")
        fields[1].setPlainText("car\npaint")
        next(b for b in form.findChildren(QPushButton) if b.text() == "Создать проект").click()
        self.assertEqual(window.catalog.project["name"], "Игра 2")
        self.assertEqual(window.selected_guids, {})
        self.assertIsNone(window.editor)
        window.project_combo.setCurrentIndex(0)
        self.assertEqual(window.catalog.project["id"], "default")


if __name__ == "__main__":
    unittest.main()
