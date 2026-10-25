import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QComboBox
from app.storage import ProjectManager, read_json, write_json
from app.structure import StructureService
from app.guid_search import GuidSearchWindow


class StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = ProjectManager(self.root)
        self.catalog = self.manager.catalog()
        self.image = self.root / "image.png"
        image = QImage(32, 32, QImage.Format_ARGB32)
        image.fill(Qt.blue)
        image.save(str(self.image))
        self.first = self.add(1, "offers", "season", "hat")
        self.second = self.add(2, "events", "season", "hat")
        self.third = self.add(3, "offers", None, "body")
        self.service = StructureService(self.manager, "default")

    def add(self, number, category, subcategory, kind):
        return self.catalog.save_item(dict(guid=f"00000000-0000-4000-8000-{number:012d}", name=f"Item {number}",
            category=category, subcategory=subcategory, type=kind), self.image)

    def rows(self):
        return {r["guid"]: r for r in self.catalog.items()}

    def apply(self, level, **kwargs):
        plan = self.service.preview_rename(level, **kwargs)
        self.service.apply(plan)
        return plan

    def window(self):
        window = GuidSearchWindow(self.manager)
        self.addCleanup(window.close)
        return window

    def wait(self, panel):
        if not panel.is_saving:
            return
        loop = QEventLoop()
        timeout = QTimer(loop)
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        panel.task.finished.connect(loop.quit)
        timeout.start(5000)
        loop.exec()
        self.assertFalse(panel.is_saving, "Structure operation did not finish")

    def select(self, panel, level, source, category=""):
        def find(parent):
            for i in range(parent.childCount()):
                item = parent.child(i)
                if item.data(0, Qt.UserRole) == {"level": level, "source": source, "category": category}:
                    return item
                match = find(item)
                if match:
                    return match
            return None
        item = find(panel.tree.invisibleRootItem())
        self.assertIsNotNone(item)
        panel.tree.setCurrentItem(item)

    def test_one_save_action_updates_tree_and_guid_output(self):
        window = self.window()
        window.selected_guids[self.first["guid"]] = "hat"
        window._open_project_form(True)
        panel = window.editor.structure
        self.select(panel, "type", "hat")
        self.assertEqual(panel.name.text(), "hat")
        self.assertFalse(panel.save_button.isEnabled())
        self.assertEqual(panel.findChildren(QComboBox), [])
        panel.name.setText("head")
        self.assertTrue(panel.save_button.isEnabled())
        panel.save_button.click()
        self.wait(panel)
        self.assertEqual(self.rows()[self.first["guid"]]["type"], "head")
        self.assertEqual(window.selected_guids[self.first["guid"]], "head")
        self.assertEqual(panel.selection()["source"], "head")
        self.assertIn('"head"', window.guid_output.toPlainText())
        panel.undo()
        self.wait(panel)
        self.assertEqual(self.rows()[self.first["guid"]]["type"], "hat")
        self.assertEqual(window.selected_guids[self.first["guid"]], "hat")

    def test_empty_category_deletion_and_undo_restore_metadata_and_file(self):
        self.manager.get("default")["subcategories"] = {"maps": ["Empty sub"]}
        path = self.catalog.data_dir / "maps.json"
        write_json(path, [])
        before = path.read_bytes()
        index_before = self.catalog.index.read_bytes()
        plan = self.service.preview_delete_category("maps")
        self.assertIn("maps", self.manager.catalog().categories())
        self.service.apply(plan)
        self.assertNotIn("maps", self.manager.catalog().categories())
        self.assertNotIn("maps", self.manager.get("default")["subcategories"])
        self.assertFalse(path.exists())
        self.assertEqual(self.catalog.index.read_bytes(), index_before)
        self.service.undo()
        self.assertIn("maps", self.manager.catalog().categories())
        self.assertEqual(self.manager.catalog().subcategories("maps"), ["Empty sub"])
        self.assertEqual(path.read_bytes(), before)

    def test_delete_category_with_items_is_rejected(self):
        before = self.catalog.index.read_bytes()
        with self.assertRaises(ValueError):
            self.service.preview_delete_category("offers")
        self.assertEqual(self.catalog.index.read_bytes(), before)
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        self.select(panel, "category", "offers")
        with patch.object(panel, "_confirm_delete_category") as confirm:
            panel.delete_category()
            confirm.assert_not_called()
        self.assertIn("элементы: 2", panel.message.text())

    def test_delete_category_requires_confirmation_and_refreshes_tree(self):
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        self.select(panel, "category", "maps")
        self.assertFalse(panel.delete_button.isHidden())
        with patch.object(panel, "_confirm_delete_category", return_value=False) as confirm:
            panel.delete_category()
            confirm.assert_called_once_with("maps")
        self.assertFalse(panel.is_saving)
        self.assertIn("maps", self.manager.catalog().categories())
        with patch.object(panel, "_confirm_delete_category", return_value=True):
            panel.delete_category()
            self.wait(panel)
        self.assertNotIn("maps", window.catalog.categories())
        self.assertEqual(window._item_count, 3)
        self.assertEqual(panel.message.text(), "Категория удалена.")
        self.select(panel, "type", "hat")
        self.assertTrue(panel.delete_button.isHidden())

    def test_failed_category_deletion_preserves_controls_and_data(self):
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        self.select(panel, "category", "maps")
        with patch.object(panel, "_confirm_delete_category", return_value=True), patch.object(
                panel.service, "apply", side_effect=OSError("read only")):
            panel.delete_category()
            self.wait(panel)
        self.assertIn("maps", self.manager.catalog().categories())
        self.assertTrue(panel.controls.isEnabled())
        self.assertIn("read only", panel.message.text())

    def test_removing_empty_case_variant_preserves_used_category_file(self):
        self.manager.get("default")["categories"].append("Offers")
        before = (self.catalog.data_dir / "offers.json").read_bytes()
        self.service.apply(self.service.preview_delete_category("Offers"))
        self.assertEqual((self.catalog.data_dir / "offers.json").read_bytes(), before)
        self.assertIn("offers", self.manager.catalog().categories())
        self.assertNotIn("Offers", self.manager.catalog().categories())

    def test_subcategory_is_selected_directly_in_tree(self):
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        self.select(panel, "subcategory", "season", "offers")
        self.assertEqual(panel.name.text(), "season")
        self.assertIn("offers", panel.selected_label.text())
        panel.name.setText("new")
        panel.save_name()
        self.wait(panel)
        self.assertEqual(self.rows()[self.first["guid"]]["subcategory"], "new")
        self.assertEqual(self.rows()[self.second["guid"]]["subcategory"], "season")

    def test_existing_name_is_rejected_without_merging(self):
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        self.select(panel, "category", "offers")
        panel.name.setText("events")
        before = self.catalog.index.read_bytes()
        panel.save_name()
        self.assertFalse(panel.is_saving)
        self.assertIn("уже существует", panel.message.text())
        self.assertEqual(self.catalog.index.read_bytes(), before)

    def test_escape_discards_unsaved_name(self):
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        self.select(panel, "category", "offers")
        panel.name.setText("New")
        before = self.catalog.index.read_bytes()
        window._go_back()
        self.assertIsNone(window.editor)
        self.assertEqual(self.catalog.index.read_bytes(), before)

    def test_background_rename_keeps_ui_active_and_blocks_closing(self):
        window = self.window()
        window.show()
        window._open_project_form(True)
        settings = window.editor
        panel = settings.structure
        self.select(panel, "category", "offers")
        panel.name.setText("Renamed")
        release = threading.Event()
        actual_apply = panel.service.apply

        def slow_apply(plan):
            release.wait(2)
            return actual_apply(plan)

        ticks = []
        with patch.object(panel.service, "apply", side_effect=slow_apply):
            panel.save_name()
            self.assertTrue(settings.is_saving)
            window._go_back()
            self.assertIs(window.editor, settings)
            window.close()
            self.assertTrue(window.isVisible())
            QTimer.singleShot(30, lambda: (ticks.append(True), release.set()))
            self.wait(panel)
        self.assertTrue(ticks)
        self.assertTrue(panel.controls.isEnabled())
        self.assertFalse(settings.is_saving)

    def test_panel_write_failure_preserves_name_and_allows_retry(self):
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        self.select(panel, "category", "offers")
        panel.name.setText("Renamed")
        before = self.catalog.index.read_bytes()
        with patch.object(panel.service, "apply", side_effect=OSError("disk unavailable")):
            panel.save_name()
            self.wait(panel)
        self.assertIn("disk unavailable", panel.message.text())
        self.assertTrue(panel.controls.isEnabled())
        self.assertEqual(panel.name.text(), "Renamed")
        self.assertEqual(self.catalog.index.read_bytes(), before)
        panel.save_name()
        self.wait(panel)
        self.assertEqual(self.rows()[self.first["guid"]]["category"], "Renamed")

    def test_preview_does_not_write_and_category_rename_updates_records(self):
        before = self.catalog.index.read_bytes()
        plan = self.service.preview_rename("category", source="offers", target="Офферы")
        self.assertEqual(plan["count"], 2)
        self.assertEqual(self.catalog.index.read_bytes(), before)
        self.service.apply(plan)
        self.assertEqual(self.rows()[self.first["guid"]]["category"], "Офферы")
        self.assertEqual(self.rows()[self.second["guid"]], self.second)
        self.assertNotIn("offers", self.manager.catalog().categories())
        self.assertEqual(read_json(self.catalog.data_dir / "offers.json", None), [])
        self.assertEqual(len(read_json(self.catalog.data_dir / "Офферы.json", [])), 2)
        self.assertEqual(self.catalog.icon(self.rows()[self.first["guid"]]), self.catalog.icon(self.first))

    def test_subcategory_rename_is_scoped_to_one_category(self):
        plan = self.apply("subcategory", source="season", target="new", category="offers")
        self.assertEqual(plan["count"], 1)
        self.assertEqual(self.rows()[self.first["guid"]]["subcategory"], "new")
        self.assertEqual(self.rows()[self.second["guid"]]["subcategory"], "season")

    def test_type_rename_affects_all_categories(self):
        plan = self.apply("type", source="hat", target="head")
        self.assertEqual(plan["count"], 2)
        self.assertNotIn("hat", self.manager.catalog().types())
        self.assertEqual(self.rows()[self.first["guid"]]["type"], "head")
        self.assertEqual(self.rows()[self.second["guid"]]["type"], "head")






    def test_rejects_collisions_and_invalid_paths(self):
        for level, target in (("category", "events"), ("category", "EVENTS"), ("category", "../oops"), ("subcategory", "CON")):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.service.preview_rename(level, source="offers" if level == "category" else "season",
                                     target=target, category="offers")

    def test_case_only_category_rename_keeps_category_file(self):
        self.apply("category", source="offers", target="Offers")
        self.assertEqual(len(read_json(self.catalog.data_dir / "Offers.json", [])), 2)

    def test_copies_group_icon_and_undo_restores_exact_bytes(self):
        old_icon = self.catalog.icons_dir / "offers/season/icon.png"
        old_icon.write_bytes(self.image.read_bytes())
        before_index = self.catalog.index.read_bytes()
        before_category = (self.catalog.data_dir / "offers.json").read_bytes()
        self.assertFalse(self.manager.path.exists())
        before_config = json.dumps(self.manager.config)
        self.apply("subcategory", source="season", target="renamed", category="offers")
        new_icon = self.catalog.icons_dir / "offers/renamed/icon.png"
        self.assertEqual(new_icon.read_bytes(), old_icon.read_bytes())
        self.assertIsNotNone(self.service.undo_info())
        self.service.undo()
        self.assertFalse(new_icon.exists())
        self.assertEqual(self.catalog.index.read_bytes(), before_index)
        self.assertEqual((self.catalog.data_dir / "offers.json").read_bytes(), before_category)
        self.assertFalse(self.manager.path.exists())
        self.assertEqual(json.dumps(self.manager.config), before_config)
        self.assertIsNone(self.service.undo_info())


    def test_undo_refuses_to_overwrite_new_items(self):
        self.apply("type", source="hat", target="head")
        self.add(4, "events", None, "head")
        with self.assertRaises(ValueError):
            self.service.undo()
        self.assertEqual(len(self.catalog.items()), 4)

    def test_undo_survives_reopening_project(self):
        before = self.catalog.index.read_bytes()
        self.apply("type", source="hat", target="head")
        reopened = ProjectManager(self.root)
        StructureService(reopened, "default").undo()
        self.assertEqual(self.catalog.index.read_bytes(), before)
        self.assertIn("hat", reopened.catalog().types())

    def test_old_preview_cannot_overwrite_new_items(self):
        plan = self.service.preview_rename("type", source="hat", target="head")
        self.add(4, "events", None, "body")
        with self.assertRaises(ValueError):
            self.service.apply(plan)
        self.assertEqual(len(self.catalog.items()), 4)

    def test_write_failure_rolls_back_all_modified_files(self):
        before = {p: p.read_bytes() for p in self.catalog.data_dir.glob("*.json")}
        original_write = self.service._write_bytes
        failed = False

        def fail_once(path, data):
            nonlocal failed
            if path.name == "offers.json" and not failed:
                failed = True
                raise OSError("disk unavailable")
            original_write(path, data)

        plan = self.service.preview_rename("category", source="offers", target="New")
        with patch.object(self.service, "_write_bytes", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.service.apply(plan)
        self.assertTrue(failed)
        self.assertEqual({p: p.read_bytes() for p in self.catalog.data_dir.glob("*.json")}, before)
        self.assertFalse(self.manager.path.exists())
        self.assertIsNone(self.service.undo_info())

    def test_only_selected_project_is_changed(self):
        self.manager.save_project("Second", ["offers"], ["hat"])
        other = self.manager.catalog()
        other.save_item(self.first, self.image)
        self.apply("type", source="hat", target="head")
        self.assertEqual(other.items()[0]["type"], "hat")






if __name__ == "__main__":
    unittest.main()
