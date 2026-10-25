"""Previewed bulk catalog changes, with file snapshots and guarded undo."""
import base64
import hashlib
import json
import uuid
from copy import deepcopy

from app.storage import read_json, write_json, valid_component


def encoded_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


class StructureService:
    def __init__(self, manager, project_id):
        self.manager = manager
        self.project_id = project_id
        self.catalog = manager.catalog(project_id)
        self.backups = manager.root / ".catalog-backups" / project_id
        self.latest = self.backups / "latest.json"

    def _path(self, relative):
        path = (self.manager.root / relative).resolve()
        if not path.is_relative_to(self.manager.root.resolve()):
            raise ValueError("Недопустимый путь в резервной копии.")
        return path

    def _relative(self, path):
        return path.resolve().relative_to(self.manager.root.resolve()).as_posix()

    def _signature(self):
        files = sorted(self.catalog.data_dir.glob("*.json")) + [self.manager.path]
        return {self._relative(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
                for p in files}

    def _names(self, records, project, level, category):
        if level == "category":
            return set(project["categories"]) | {r["category"] for r in records}
        if level == "type":
            return set(project["types"]) | {r["type"] for r in records}
        return set(project.get("subcategories", {}).get(category, [])) | {
            r["subcategory"] for r in records if r.get("category") == category and r.get("subcategory")}

    def preview_rename(self, level, source, target, category=""):
        if level not in {"category", "subcategory", "type"}:
            raise ValueError("Выберите категорию, подкатегорию или тип.")
        records = self.catalog.items()
        project = deepcopy(self.manager.get(self.project_id))
        names = self._names(records, project, level, category)
        if source not in names:
            raise ValueError("Выберите название в дереве.")
        target = target.strip()
        if not target:
            raise ValueError("Введите название.")
        if level != "type":
            target = valid_component(target)
        if target == source:
            raise ValueError("Название не изменилось.")
        collision = target in names or (level != "type" and any(
            name != source and name.casefold() == target.casefold() for name in names))
        if collision:
            raise ValueError("Такое название уже существует. Введите другое название.")

        def matches(rec):
            return rec.get(level) == source and (level != "subcategory" or rec.get("category") == category)

        affected = [r for r in records if matches(r)]
        updated = deepcopy(records)
        for rec in updated:
            if matches(rec):
                rec[level] = target
        subs = project.setdefault("subcategories", {})
        if level == "subcategory":
            values = subs.setdefault(category, [])
        else:
            values = project["categories" if level == "category" else "types"]
        values[:] = [target if name == source else name for name in values]
        if target not in values:
            values.append(target)
        if level == "category" and source in subs:
            subs[target] = subs.pop(source)

        config = deepcopy(self.manager.config)
        config["projects"] = [project if p["id"] == self.project_id else p for p in config["projects"]]
        files = {self.catalog.index: encoded_json(updated), self.manager.path: encoded_json(config)}
        for name in {r["category"] for r in records + updated} | set(project["categories"]):
            valid_component(name)
            files[self.catalog.data_dir / f"{name}.json"] = encoded_json([r for r in updated if r["category"].casefold() == name.casefold()])

        # Existing item image paths remain valid; group icons follow renamed branches.
        folders = []
        if level == "category":
            for sub in self._names(records, self.manager.get(self.project_id), "subcategory", source):
                folders.append((source, sub, target, sub))
        elif level == "subcategory":
            folders.append((category, source, category, target))
        for old_cat, old_sub, new_cat, new_sub in folders:
            old_folder = self.catalog.icons_dir / valid_component(old_cat) / valid_component(old_sub)
            new_folder = self.catalog.icons_dir / valid_component(new_cat) / valid_component(new_sub)
            extensions = (".png", ".jpg", ".jpeg", ".webp")
            if any((new_folder / f"icon{ext}").exists() for ext in extensions):
                continue
            for ext in extensions:
                old_icon = old_folder / f"icon{ext}"
                if old_icon.is_file():
                    files[new_folder / f"icon{ext}"] = old_icon.read_bytes()

        description = f'Переименовать «{source}» в «{target}».'
        if level == "subcategory":
            description += f' В категории «{category}».'
        if level == "type":
            description += " Изменится также ключ в выводе выбранных GUID."
        return {"files": files, "signature": self._signature(), "count": len(affected),
                "description": description, "project": project}

    def preview_delete_category(self, source):
        source = valid_component(source)
        records = self.catalog.items()
        project = deepcopy(self.manager.get(self.project_id))
        if source not in self._names(records, project, "category", ""):
            raise ValueError("Выберите существующую категорию.")
        count = sum(r.get("category") == source for r in records)
        if count:
            raise ValueError(f"В категории есть элементы: {count}. Сначала перенесите или удалите их.")
        project["categories"] = [name for name in project["categories"] if name != source]
        project.setdefault("subcategories", {}).pop(source, None)
        config = deepcopy(self.manager.config)
        config["projects"] = [project if p["id"] == self.project_id else p for p in config["projects"]]
        files = {self.manager.path: encoded_json(config)}
        # Windows can map another category with different letter case to the same file.
        if not any(r.get("category", "").casefold() == source.casefold() for r in records):
            files[self.catalog.data_dir / f"{source}.json"] = None
        return {"files": files, "signature": self._signature(), "count": 0,
                "description": f'Удалить пустую категорию «{source}».',
                "project": project, "operation": "delete_category"}

    def _write_bytes(self, path, data):
        self._path(self._relative(path))
        if data is None:
            if path.exists():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _commit(self, files, finish):
        before = {path: path.read_bytes() if path.exists() else None for path in files}
        written = []
        try:
            for path, data in files.items():
                written.append(path)
                self._write_bytes(path, data)
            finish()
        except Exception:
            for path in reversed(written):
                self._write_bytes(path, before[path])
            raise

    def apply(self, plan):
        if self._signature() != plan["signature"]:
            raise ValueError("Каталог изменился после предпросмотра. Проверьте изменение заново.")
        backup = self.backups / uuid.uuid4().hex / "backup.json"
        files = plan["files"]
        before = {self._relative(p): base64.b64encode(p.read_bytes()).decode() if p.exists() else None for p in files}
        state = {"before": before, "description": plan["description"], "count": plan["count"],
                 "config_before": deepcopy(self.manager.config)}
        write_json(backup, state)

        def finish():
            state["after_signature"] = self._signature()
            state["after_hashes"] = {self._relative(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in files}
            write_json(backup, state)
            write_json(self.latest, {"backup": self._relative(backup)})

        self._commit(files, finish)
        self.manager.config = read_json(self.manager.path, state["config_before"])
        self.catalog = self.manager.catalog(self.project_id)
        return plan["count"]

    def undo_info(self):
        marker = read_json(self.latest, {})
        if not marker.get("backup"):
            return None
        backup = self._path(marker["backup"])
        if not backup.is_relative_to(self.backups.resolve()):
            raise ValueError("Некорректная резервная копия.")
        state = read_json(backup, {})
        return state if "after_signature" in state else None

    def undo(self):
        state = self.undo_info()
        if state is None:
            raise ValueError("Нет изменения структуры для отмены.")
        if self._signature() != state["after_signature"]:
            raise ValueError("После этого изменения каталог или настройки уже менялись. Отмена недоступна, чтобы не потерять новые данные.")
        for relative, expected in state["after_hashes"].items():
            path = self._path(relative)
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            if actual != expected:
                raise ValueError("После изменения были обновлены файлы. Автоматическая отмена недоступна.")
        files = {self._path(relative): base64.b64decode(value) if value is not None else None
                 for relative, value in state["before"].items()}
        self._commit(files, lambda: write_json(self.latest, {"backup": None}))
        self.manager.config = read_json(self.manager.path, state["config_before"])
        self.catalog = self.manager.catalog(self.project_id)
        return state["count"]
