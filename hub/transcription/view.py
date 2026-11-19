from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from hub.storage import TranscriptsRepo
from hub.transcription import engine


class Worker(QObject):
    progress = Signal(float)
    done = Signal(int, str, str, str)  # id, texte, langue, erreur

    def __init__(self, tid: int, path: str, language: str | None):
        super().__init__()
        self.tid, self.path, self.language = tid, path, language

    def run(self):
        try:
            text, lang = engine.transcribe(Path(self.path), self.language, self.progress.emit)
            self.done.emit(self.tid, text, lang, "")
        except Exception as e:  # modèle absent, hors ligne au 1er lancement, etc.
            self.done.emit(self.tid, "", "", str(e))


class TranscriptionView(QWidget):
    def __init__(self, repo: TranscriptsRepo):
        super().__init__()
        self.repo = repo
        self.rec = engine.Recorder()
        self.current: int | None = None
        self._thread: QThread | None = None
        self._save_timer = QTimer(self, singleShot=True, interval=800)
        self._save_timer.timeout.connect(self.save)
        self._tick = QTimer(self, interval=200)
        self._tick.timeout.connect(self._update_rec)

        # Barre d'enregistrement
        self.rec_btn = QPushButton("● Enregistrer")
        self.rec_btn.clicked.connect(lambda: self.toggle_record())
        self.lang = QComboBox()
        for label, code in (("Langue auto", None), ("Français", "fr"), ("Anglais", "en")):
            self.lang.addItem(label, code)
        self.lang.setCurrentIndex(1)
        self.rec_info = QLabel()
        self.level = QProgressBar(maximum=100, textVisible=False)
        self.level.setFixedWidth(120)
        self.progress = QProgressBar(maximum=100)
        self.progress.hide()
        top = QHBoxLayout()
        top.addWidget(self.rec_btn)
        top.addWidget(self.lang)
        top.addWidget(self.level)
        top.addWidget(self.rec_info, 1)
        top.addWidget(self.progress)

        # Liste
        self.search = QLineEdit(placeholderText="Rechercher")
        self.search.textChanged.connect(lambda *_: self.reload())
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._open)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.search)
        ll.addWidget(self.list, 1)

        # Détail
        self.title = QLineEdit(placeholderText="Titre")
        self.title.textEdited.connect(self._changed)
        self.text = QTextEdit()
        self.text.setAcceptRichText(False)
        self.text.textChanged.connect(self._changed)
        self.meta = QLabel()
        self.retry_btn = QPushButton("Retranscrire")
        self.retry_btn.clicked.connect(self.retranscribe)
        self.del_btn = QPushButton("Supprimer")
        self.del_btn.clicked.connect(self.delete)
        btns = QHBoxLayout()
        btns.addWidget(self.meta, 1)
        btns.addWidget(self.retry_btn)
        btns.addWidget(self.del_btn)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.title)
        rl.addWidget(self.text, 1)
        rl.addLayout(btns)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([280, 800])
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        self._enable_detail(False)
        self.reload()

    # ----- liste -----
    def reload(self):
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.repo.list(self.search.text()):
            date = datetime.fromtimestamp(r["created_at"]).strftime("%d/%m/%Y %H:%M")
            status = "" if r["text"] else "  (non transcrit)"
            it = QListWidgetItem(f"{r['title']}{status}\n{date} · {int(r['duration'])} s")
            it.setData(Qt.UserRole, r["id"])
            self.list.addItem(it)
            if r["id"] == self.current:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)

    def _open(self, item, _prev=None):
        if not item:
            return
        self.save()
        self._load(item.data(Qt.UserRole))

    def _load(self, tid: int):
        r = self.repo.get(tid)
        if not r:
            return
        self.current = tid
        for w in (self.title, self.text):
            w.blockSignals(True)
        self.title.setText(r["title"])
        self.text.setPlainText(r["text"])
        for w in (self.title, self.text):
            w.blockSignals(False)
        self.meta.setText(f"Durée {int(r['duration'])} s · langue {r['language'] or '?'} · {r['audio_path']}")
        self._enable_detail(True)

    def _enable_detail(self, on: bool):
        for w in (self.title, self.text, self.retry_btn, self.del_btn):
            w.setEnabled(on)
        if not on:
            self.title.clear()
            self.text.clear()
            self.meta.clear()

    def _changed(self, *_):
        if self.current is not None:
            self._save_timer.start()

    def save(self):
        if self.current is None:
            return
        self._save_timer.stop()
        self.repo.update(self.current, title=self.title.text().strip() or "Sans titre",
                         text=self.text.toPlainText())

    def delete(self):
        if self.current is None:
            return
        if QMessageBox.question(self, "Supprimer", "Supprimer cette transcription et son audio ?") \
                == QMessageBox.Yes:
            self._save_timer.stop()
            self.repo.delete(self.current)
            self.current = None
            self._enable_detail(False)
            self.reload()

    # ----- enregistrement -----
    def toggle_record(self, transcribe: bool = True):
        if self.rec.recording:
            path = engine.audio_dir() / f"rec_{int(time.time())}.wav"
            self._tick.stop()
            self.level.setValue(0)
            duration = self.rec.stop(path)
            self.rec_btn.setText("● Enregistrer")
            self.rec_info.clear()
            if duration < 0.5:
                path.unlink(missing_ok=True)
                self.rec_info.setText("Enregistrement trop court.")
                return
            title = datetime.now().strftime("Enregistrement %d/%m/%Y %H:%M")
            tid = self.repo.create(title, str(path), duration)
            self.save()
            self.current = tid
            self.reload()
            self._load(tid)
            if transcribe:
                self._start_transcription(tid, str(path))
        else:
            try:
                self.rec.start()
            except Exception as e:
                QMessageBox.warning(self, "Micro", f"Impossible d'ouvrir le micro : {e}")
                return
            self.rec_btn.setText("■ Arrêter")
            self._tick.start()

    def _update_rec(self):
        s = int(self.rec.elapsed())
        self.rec_info.setText(f"Enregistrement... {s // 60:02d}:{s % 60:02d}")
        self.level.setValue(int(min(self.rec.level, 1.0) * 100))

    # ----- transcription -----
    def retranscribe(self):
        r = self.repo.get(self.current) if self.current else None
        if r and Path(r["audio_path"]).exists():
            self._start_transcription(r["id"], r["audio_path"])
        elif r:
            QMessageBox.warning(self, "Audio", "Fichier audio introuvable.")

    def _start_transcription(self, tid: int, path: str):
        if self._thread:
            QMessageBox.information(self, "Transcription", "Une transcription est déjà en cours.")
            return
        self.progress.setValue(0)
        self.progress.show()
        self.retry_btn.setEnabled(False)
        self.rec_info.setText("Transcription... (1er usage : téléchargement du modèle)")
        self._thread = QThread()
        self._worker = Worker(tid, path, self.lang.currentData())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda f: self.progress.setValue(int(f * 100)))
        self._worker.done.connect(self._done)
        self._thread.start()

    def _done(self, tid: int, text: str, lang: str, err: str):
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self.progress.hide()
        self.retry_btn.setEnabled(self.current is not None)
        if err:
            self.rec_info.setText("")
            QMessageBox.warning(self, "Transcription", f"Échec : {err}")
            return
        self.repo.update(tid, text=text, language=lang)
        self.rec_info.setText("Transcription terminée.")
        self.reload()
        if tid == self.current:
            self._load(tid)

    def shutdown(self):
        self.save()
        if self.rec.recording:
            self.toggle_record(transcribe=False)
        if self._thread:  # transcription en cours : on attend sa fin (pas d'arrêt brutal)
            self._thread.quit()
            self._thread.wait()
