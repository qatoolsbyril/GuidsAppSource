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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.storage import ProjectManager, read_json
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

    def apply(self, level, action, **kwargs):
        plan = self.service.preview(level, action, **kwargs)
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

    def test_preview_does_not_write_and_category_rename_updates_records(self):
        before = self.catalog.index.read_bytes()
        plan = self.service.preview("category", "rename", source="offers", target="Офферы")
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
        plan = self.apply("subcategory", "rename", source="season", target="new", category="offers")
        self.assertEqual(plan["count"], 1)
        self.assertEqual(self.rows()[self.first["guid"]]["subcategory"], "new")
        self.assertEqual(self.rows()[self.second["guid"]]["subcategory"], "season")

    def test_type_rename_affects_all_categories(self):
        plan = self.apply("type", "rename", source="hat", target="head")
        self.assertEqual(plan["count"], 2)
        self.assertNotIn("hat", self.manager.catalog().types())
        self.assertEqual(self.rows()[self.first["guid"]]["type"], "head")
        self.assertEqual(self.rows()[self.second["guid"]]["type"], "head")

    def test_category_merge_preserves_guids(self):
        self.apply("category", "merge", source="offers", target="events")
        rows = self.catalog.items()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["category"] for r in rows}, {"events"})
        self.assertEqual(len({r["guid"] for r in rows}), 3)

    def test_move_subcategory_merges_with_destination(self):
        self.apply("subcategory", "move", source="season", category="offers", destination="events")
        self.assertEqual(self.rows()[self.first["guid"]]["category"], "events")
        self.assertEqual(self.rows()[self.third["guid"]]["category"], "offers")
        self.assertEqual(self.manager.catalog().subcategories("events"), ["season"])

    def test_flatten_keeps_items(self):
        self.apply("subcategory", "flatten", source="season", category="offers")
        self.assertIsNone(self.rows()[self.first["guid"]]["subcategory"])
        self.assertEqual(len(self.catalog.items()), 3)

    def test_add_and_remove_empty_names(self):
        self.apply("category", "add", target="Empty")
        self.apply("subcategory", "add", target="Sub", category="Empty")
        self.assertIn("Sub", self.manager.catalog().subcategories("Empty"))
        with self.assertRaises(ValueError):
            self.service.preview("category", "remove", source="Empty")
        self.apply("subcategory", "remove", source="Sub", category="Empty")
        self.apply("category", "remove", source="Empty")
        self.assertNotIn("Empty", self.manager.catalog().categories())
        self.apply("type", "add", target="custom")
        self.apply("type", "remove", source="custom")
        self.assertNotIn("custom", self.manager.catalog().types())

    def test_filled_branch_requires_transfer(self):
        for level, source, category in (("category", "offers", ""), ("type", "hat", ""), ("subcategory", "season", "offers")):
            with self.subTest(level=level), self.assertRaises(ValueError):
                self.service.preview(level, "remove", source=source, category=category)

    def test_rejects_collisions_and_invalid_paths(self):
        for level, target in (("category", "events"), ("category", "EVENTS"), ("category", "../oops"), ("subcategory", "CON")):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.service.preview(level, "rename", source="offers" if level == "category" else "season",
                                     target=target, category="offers")

    def test_case_only_category_rename_keeps_category_file(self):
        self.apply("category", "rename", source="offers", target="Offers")
        self.assertEqual(len(read_json(self.catalog.data_dir / "Offers.json", [])), 2)

    def test_copies_group_icon_and_undo_restores_exact_bytes(self):
        old_icon = self.catalog.icons_dir / "offers/season/icon.png"
        old_icon.write_bytes(self.image.read_bytes())
        before_index = self.catalog.index.read_bytes()
        before_category = (self.catalog.data_dir / "offers.json").read_bytes()
        self.assertFalse(self.manager.path.exists())
        before_config = json.dumps(self.manager.config)
        self.apply("subcategory", "rename", source="season", target="renamed", category="offers")
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

    def test_merge_keeps_destination_group_icon(self):
        destination_icon = self.catalog.icons_dir / "events/season/icon.jpg"
        destination_icon.write_bytes(b"destination")
        (self.catalog.icons_dir / "offers/season/icon.png").write_bytes(self.image.read_bytes())
        self.apply("category", "merge", source="offers", target="events")
        self.assertEqual(destination_icon.read_bytes(), b"destination")
        self.assertFalse((self.catalog.icons_dir / "events/season/icon.png").exists())

    def test_undo_refuses_to_overwrite_new_items(self):
        self.apply("type", "rename", source="hat", target="head")
        self.add(4, "events", None, "head")
        with self.assertRaises(ValueError):
            self.service.undo()
        self.assertEqual(len(self.catalog.items()), 4)

    def test_undo_survives_reopening_project(self):
        before = self.catalog.index.read_bytes()
        self.apply("type", "rename", source="hat", target="head")
        reopened = ProjectManager(self.root)
        StructureService(reopened, "default").undo()
        self.assertEqual(self.catalog.index.read_bytes(), before)
        self.assertIn("hat", reopened.catalog().types())

    def test_old_preview_cannot_overwrite_new_items(self):
        plan = self.service.preview("type", "rename", source="hat", target="head")
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

        plan = self.service.preview("category", "rename", source="offers", target="New")
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
        self.apply("type", "rename", source="hat", target="head")
        self.assertEqual(other.items()[0]["type"], "hat")

    def test_panel_preview_confirm_and_undo_updates_tree_and_guid_output(self):
        window = self.window()
        window.selected_guids[self.first["guid"]] = "hat"
        window._open_project_form(True)
        settings = window.editor
        panel = settings.structure
        panel.scope.setCurrentIndex(panel.scope.findData("type"))
        panel.types.setCurrentRow(next(i for i in range(panel.types.count()) if panel.types.item(i).data(Qt.UserRole) == "hat"))
        panel.target.setCurrentText("head")
        panel.preview_change()
        self.assertEqual(panel.pending["count"], 2)
        self.assertEqual(self.rows()[self.first["guid"]]["type"], "hat")
        panel.apply_pending()
        self.wait(panel)
        self.assertEqual(self.rows()[self.first["guid"]]["type"], "head")
        self.assertEqual(window.selected_guids[self.first["guid"]], "head")
        self.assertIn('"head"', window.guid_output.toPlainText())
        panel.preview_undo()
        panel.apply_pending()
        self.wait(panel)
        self.assertEqual(self.rows()[self.first["guid"]]["type"], "hat")
        self.assertEqual(window.selected_guids[self.first["guid"]], "hat")

    def test_escape_cancels_preview_before_closing_settings(self):
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        panel.target.setCurrentText("New")
        panel.preview_change()
        self.assertIsNotNone(panel.pending)
        window._go_back()
        self.assertIsNotNone(window.editor)
        self.assertIsNone(panel.pending)
        window._go_back()
        self.assertIsNone(window.editor)

    def test_background_change_keeps_ui_active_and_blocks_closing(self):
        window = self.window()
        window.show()
        window._open_project_form(True)
        settings = window.editor
        settings.tabs.setCurrentIndex(1)
        panel = settings.structure
        panel.target.setCurrentText("Renamed")
        panel.preview_change()
        release = threading.Event()
        actual_apply = panel.service.apply

        def slow_apply(plan):
            release.wait(2)
            return actual_apply(plan)

        ticks = []
        with patch.object(panel.service, "apply", side_effect=slow_apply):
            panel.apply_pending()
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

    def test_panel_write_failure_restores_controls(self):
        window = self.window()
        window._open_project_form(True)
        panel = window.editor.structure
        panel.target.setCurrentText("Renamed")
        panel.preview_change()
        before = self.catalog.index.read_bytes()
        with patch.object(panel.service, "apply", side_effect=OSError("disk unavailable")):
            panel.apply_pending()
            self.wait(panel)
        self.assertIn("disk unavailable", panel.message.text())
        self.assertTrue(panel.controls.isEnabled())
        self.assertIsNone(panel.pending)
        self.assertEqual(self.catalog.index.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
