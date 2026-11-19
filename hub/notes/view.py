"""Module notes : dossiers (arborescence), tags, épinglage, recherche plein texte, tri."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from hub.notes.editor import EditorWidget
from hub.storage import NotesRepo

ALL, NONE = -1, -2  # pseudo-dossiers


class NotesView(QWidget):
    def __init__(self, repo: NotesRepo):
        super().__init__()
        self.repo = repo
        self.current: int | None = None
        self._save_timer = QTimer(self, singleShot=True, interval=800)
        self._save_timer.timeout.connect(self.save)

        # Colonne 1 : dossiers + tags
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._folder_menu)
        self.tree.currentItemChanged.connect(lambda *_: self.reload_list())
        new_folder = QPushButton("+ Dossier")
        new_folder.clicked.connect(self.add_folder)
        self.tag_box = QComboBox()
        self.tag_box.currentIndexChanged.connect(lambda *_: self.reload_list())
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.tree, 1)
        ll.addWidget(new_folder)
        ll.addWidget(QLabel("Filtrer par tag"))
        ll.addWidget(self.tag_box)

        # Colonne 2 : recherche + liste
        self.search = QLineEdit(placeholderText="Rechercher (titre, contenu, tags)")
        self.search.textChanged.connect(lambda *_: self.reload_list())
        self.sort = QComboBox()
        self.sort.addItem("Modifiées récemment", "updated")
        self.sort.addItem("Créées récemment", "created")
        self.sort.addItem("Titre A→Z", "title")
        self.sort.currentIndexChanged.connect(lambda *_: self.reload_list())
        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._note_menu)
        self.list.currentItemChanged.connect(self._open_selected)
        new_note = QPushButton("+ Nouvelle note")
        new_note.clicked.connect(self.new_note)
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(new_note)
        ml.addWidget(self.search)
        ml.addWidget(self.sort)
        ml.addWidget(self.list, 1)

        # Colonne 3 : éditeur
        self.title = QLineEdit(placeholderText="Titre")
        f = self.title.font()
        f.setPointSize(14)
        self.title.setFont(f)
        self.title.textEdited.connect(self._changed)
        self.tags = QLineEdit(placeholderText="Tags séparés par des virgules")
        self.tags.editingFinished.connect(self._save_tags)
        self.editor = EditorWidget()
        self.editor.changed.connect(self._changed)
        self.info = QLabel()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.title)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tags"))
        row.addWidget(self.tags, 1)
        row.addWidget(self.info)
        rl.addLayout(row)
        rl.addWidget(self.editor, 1)

        split = QSplitter()
        for w in (left, mid, right):
            split.addWidget(w)
        split.setSizes([180, 260, 800])
        lay = QHBoxLayout(self)
        lay.addWidget(split)

        self._set_editor_enabled(False)
        self.reload_folders()

    # ----- dossiers -----
    def reload_folders(self, select: int | None = None):
        keep = select if select is not None else self._folder_id()
        self.tree.blockSignals(True)
        self.tree.clear()
        items: dict[int, QTreeWidgetItem] = {}
        root_all = QTreeWidgetItem(["Toutes les notes"])
        root_all.setData(0, Qt.UserRole, ALL)
        root_none = QTreeWidgetItem(["Sans dossier"])
        root_none.setData(0, Qt.UserRole, NONE)
        self.tree.addTopLevelItems([root_all, root_none])
        rows = self.repo.folders()
        for r in rows:
            it = QTreeWidgetItem([r["name"]])
            it.setData(0, Qt.UserRole, r["id"])
            items[r["id"]] = it
        for r in rows:
            parent = items.get(r["parent_id"])
            (parent.addChild if parent else self.tree.addTopLevelItem)(items[r["id"]])
        self.tree.expandAll()
        target = items.get(keep) if keep not in (None, ALL, NONE) else (root_none if keep == NONE else root_all)
        self.tree.setCurrentItem(target or root_all)
        self.tree.blockSignals(False)
        self._reload_tags()
        self.reload_list()

    def _folder_id(self) -> int | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else ALL

    def add_folder(self, parent_id: int | None = None):
        name, ok = QInputDialog.getText(self, "Nouveau dossier", "Nom :")
        if ok and name.strip():
            fid = self.repo.add_folder(name.strip(), parent_id if isinstance(parent_id, int) else None)
            self.reload_folders(fid)

    def _folder_menu(self, pos):
        it = self.tree.itemAt(pos)
        fid = it.data(0, Qt.UserRole) if it else None
        m = QMenu(self)
        m.addAction("Nouveau dossier", lambda: self.add_folder(None))
        if isinstance(fid, int) and fid > 0:
            m.addAction("Nouveau sous-dossier", lambda: self.add_folder(fid))
            m.addAction("Renommer", lambda: self._rename_folder(fid, it.text(0)))
            m.addAction("Supprimer (notes conservées)", lambda: self._delete_folder(fid, it.text(0)))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _rename_folder(self, fid, old):
        name, ok = QInputDialog.getText(self, "Renommer", "Nom :", text=old)
        if ok and name.strip():
            self.repo.rename_folder(fid, name.strip())
            self.reload_folders(fid)

    def _delete_folder(self, fid, name):
        if QMessageBox.question(self, "Supprimer", f"Supprimer le dossier « {name} » et ses sous-dossiers ?\n"
                                "Les notes passent dans « Sans dossier ».") == QMessageBox.Yes:
            self.repo.delete_folder(fid)
            self.reload_folders(ALL)

    def _reload_tags(self):
        cur = self.tag_box.currentData()
        self.tag_box.blockSignals(True)
        self.tag_box.clear()
        self.tag_box.addItem("(tous)", None)
        for t in self.repo.all_tags():
            self.tag_box.addItem(t, t)
        idx = self.tag_box.findData(cur)
        self.tag_box.setCurrentIndex(max(0, idx))
        self.tag_box.blockSignals(False)

    # ----- liste -----
    def reload_list(self):
        fid = self._folder_id()
        rows = self.repo.search(
            self.search.text(),
            folder_id=None if fid == NONE else fid,
            all_folders=fid == ALL,
            tag=self.tag_box.currentData(),
            sort=self.sort.currentData() or "updated",
        )
        self.list.blockSignals(True)
        self.list.clear()
        sel = None
        for r in rows:
            date = datetime.fromtimestamp(r["updated_at"]).strftime("%d/%m/%Y %H:%M")
            text = ("★ " if r["pinned"] else "") + (r["title"] or "Sans titre") + f"\n{date}"
            if r["tags"]:
                text += f" · {r['tags']}"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, r["id"])
            self.list.addItem(it)
            if r["id"] == self.current:
                sel = it
        if sel:
            self.list.setCurrentItem(sel)
        self.list.blockSignals(False)

    def _note_menu(self, pos):
        it = self.list.itemAt(pos)
        if not it:
            return
        nid = it.data(Qt.UserRole)
        note = self.repo.get(nid)
        m = QMenu(self)
        m.addAction("Désépingler" if note.pinned else "Épingler", lambda: self._pin(nid, not note.pinned))
        mv = m.addMenu("Déplacer vers")
        mv.addAction("Sans dossier", lambda: self._move(nid, None))
        for r in self.repo.folders():
            mv.addAction(r["name"], lambda fid=r["id"]: self._move(nid, fid))
        m.addSeparator()
        m.addAction("Supprimer", lambda: self._delete(nid, note.title))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def _pin(self, nid, pinned):
        self.repo.set_pinned(nid, pinned)
        self.reload_list()

    def _move(self, nid, fid):
        self.repo.move(nid, fid)
        self.reload_list()

    def _delete(self, nid, title):
        if QMessageBox.question(self, "Supprimer", f"Supprimer la note « {title or 'Sans titre'} » ?") \
                == QMessageBox.Yes:
            if nid == self.current:
                self._save_timer.stop()
                self.current = None
                self._set_editor_enabled(False)
            self.repo.delete(nid)
            self._reload_tags()
            self.reload_list()

    # ----- édition -----
    def new_note(self):
        self.save()
        fid = self._folder_id()
        nid = self.repo.create(fid if isinstance(fid, int) and fid > 0 else None)
        self.current = nid
        self.search.clear()
        self.reload_list()
        self._load(nid)
        self.title.selectAll()
        self.title.setFocus()

    def _open_selected(self, item, _prev=None):
        if not item:
            return
        nid = item.data(Qt.UserRole)
        if nid != self.current:
            self.save()
            self._load(nid)

    def _load(self, nid: int):
        note = self.repo.get(nid)
        if not note:
            return
        self.current = nid
        self.title.setText(note.title)
        self.tags.setText(note.tags)
        self.editor.set_html(note.html)
        self._set_editor_enabled(True)
        self.info.setText("Enregistré")

    def _set_editor_enabled(self, on: bool):
        for w in (self.title, self.tags, self.editor):
            w.setEnabled(on)
        if not on:
            self.title.clear()
            self.tags.clear()
            self.editor.set_html("")

    def _changed(self, *_):
        if self.current is not None:
            self.info.setText("Modifié...")
            self._save_timer.start()

    def _save_tags(self):
        if self.current is not None:
            self.repo.set_tags(self.current, self.tags.text())
            self.tags.setText(self.repo.get(self.current).tags)
            self._reload_tags()
            self.reload_list()

    def save(self):
        if self.current is None or not self.title.isEnabled():
            return
        self._save_timer.stop()
        self.repo.save(self.current, self.title.text().strip() or "Sans titre",
                       self.editor.html(), self.editor.plain())
        self.info.setText("Enregistré")
        # rafraîchit le titre dans la liste sans perdre la sélection
        it = self.list.currentItem()
        if it and it.data(Qt.UserRole) == self.current:
            self.reload_list()
