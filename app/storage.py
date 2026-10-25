"""Local project catalogs. The original catalog stays in its original location."""
import json
import os
import shutil
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CATEGORIES = ["arrows", "offers", "battle_pass", "events", "maps"]
DEFAULT_TYPES = ["arrows", "bow", "hat", "body", "beard", "emojis", "glasses", "phrases", "stickers"]


def application_root():
    if os.getenv("GUIDS_APP_ROOT"):
        return Path(os.environ["GUIDS_APP_ROOT"]).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def valid_component(value):
    value = value.strip()
    if (not value or value in {".", ".."} or value.endswith((".", " "))
            or any(c in value for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in value)
            or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}):
        raise ValueError("Название категории или подкатегории содержит недопустимые символы.")
    if value.casefold() == "_all":
        raise ValueError("Название _all зарезервировано для общего индекса.")
    return value


class ProjectManager:
    def __init__(self, root=None):
        self.root = Path(root) if root else application_root()
        self.path = self.root / "projects.json"
        self.config = read_json(self.path, {
            "active": "default",
            "projects": [{"id": "default", "name": "Основной проект",
                          "categories": DEFAULT_CATEGORIES, "types": DEFAULT_TYPES}],
        })

    @property
    def projects(self):
        return self.config["projects"]

    def get(self, project_id):
        return next(p for p in self.projects if p["id"] == project_id)

    def select(self, project_id):
        self.get(project_id)
        updated = deepcopy(self.config)
        updated["active"] = project_id
        write_json(self.path, updated)
        self.config = updated

    def save_project(self, name, categories, types, project_id=None):
        name = name.strip()
        if not name:
            raise ValueError("Введите название проекта.")
        if any(p["name"].casefold() == name.casefold() and p["id"] != project_id for p in self.projects):
            raise ValueError("Проект с таким названием уже существует.")
        categories = list(dict.fromkeys(valid_component(c) for c in categories if c.strip()))
        types = list(dict.fromkeys(t.strip() for t in types if t.strip()))
        if not types:
            raise ValueError("Укажите хотя бы один тип кастомизации.")
        updated = deepcopy(self.config)
        project = next(p for p in updated["projects"] if p["id"] == project_id) if project_id else {"id": uuid.uuid4().hex}
        project.update(name=name, categories=categories, types=types)
        if not project_id:
            updated["projects"].append(project)
        updated["active"] = project["id"]
        write_json(self.path, updated)
        self.config = updated
        return project

    def catalog(self, project_id=None):
        return Catalog(self.root, self.get(project_id or self.config["active"]))


class Catalog:
    def __init__(self, root, project):
        self.project = project
        self.root = root if project["id"] == "default" else root / "projects" / project["id"]
        self.data_dir = self.root / "data"
        self.icons_dir = self.root / "assets" / "icons"
        self.index = self.data_dir / "_all.json"

    def items(self):
        records = read_json(self.index, [])
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise ValueError(f"Некорректный каталог: {self.index}")
        return records

    def categories(self):
        return sorted(set(self.project["categories"]) | {r["category"] for r in self.items() if r.get("category")})

    def types(self):
        return sorted(set(self.project["types"]) | {r["type"] for r in self.items() if r.get("type")})

    def subcategories(self, category):
        return sorted({r["subcategory"] for r in self.items() if r.get("category") == category and r.get("subcategory")})

    def icon(self, record):
        value = record.get("icon_path")
        if not value:
            return None
        path = (self.root / value).resolve()
        return path if path.is_relative_to(self.root.resolve()) and path.is_file() else None

    def delete_item(self, guid):
        records = self.items()
        original = next((r for r in records if r.get("guid") == guid), None)
        if original is None:
            raise ValueError("Элемент уже удалён или отсутствует в этом проекте.")
        remaining = [r for r in records if r.get("guid") != guid]
        category = valid_component(original["category"])
        category_path = self.data_dir / f"{category}.json"
        previous_category = read_json(category_path, [])
        write_json(category_path,
                   [r for r in remaining if r.get("category") == category])
        try:
            write_json(self.index, remaining)
        except OSError:
            write_json(category_path, previous_category)
            raise
        # Retain image files: they may also be referenced by other records.
        return original

    def save_item(self, record, main_icon=None, sub_icon=None, original=None):
        records = self.items()
        record = dict(record)
        try:
            record["guid"] = str(uuid.UUID(record["guid"].strip()))
        except ValueError:
            raise ValueError("Введите GUID в формате UUID.") from None
        if any(str(r.get("guid", "")).casefold() == record["guid"].casefold()
               and (original is None or r.get("guid") != original["guid"]) for r in records):
            raise ValueError("Такой GUID уже существует в этом проекте.")
        record["category"] = valid_component(record["category"])
        if record.get("subcategory"):
            record["subcategory"] = valid_component(record["subcategory"])
        if not record["name"].strip() or not record["type"].strip():
            raise ValueError("Укажите название и тип кастомизации.")
        if original is None and main_icon is None:
            raise ValueError("Добавьте иконку элемента.")
        destination = self.icons_dir / record["category"]
        if record.get("subcategory"):
            destination /= record["subcategory"]
        for source, stem in ((main_icon, record["guid"]), (sub_icon if record.get("subcategory") else None, "icon")):
            if source:
                source = Path(source)
                destination.mkdir(parents=True, exist_ok=True)
                target = destination / (stem + source.suffix.lower())
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
                if stem != "icon":
                    record["icon_path"] = target.relative_to(self.root).as_posix()
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        records = [r for r in records if not original or r.get("guid") != original["guid"]]
        records.append(record)
        # The index is authoritative; category files are maintained for compatibility.
        write_json(self.index, records)
        categories = {record["category"]}
        if original:
            categories.add(original["category"])
        for category in categories:
            write_json(self.data_dir / f"{valid_component(category)}.json",
                       [r for r in records if r.get("category") == category])
        return record
