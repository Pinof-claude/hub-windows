"""Smoke test UI hors écran : construction des vues et aller-retour HTML de l'éditeur."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_main_window(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from hub.app import MainWindow
    w = MainWindow()
    n = w.notes
    n.new_note()
    n.title.setText("Test")
    ed = n.editor
    ed.ed.setPlainText("Titre\nligne")
    c = ed.ed.textCursor()
    c.movePosition(QTextCursor.Start)
    ed.ed.setTextCursor(c)
    ed.set_style(1)
    from PySide6.QtGui import QTextListFormat
    ed._list(QTextListFormat.ListDecimal)
    ed._indent(1)
    ed._indent(-1)
    ed._list(QTextListFormat.ListDecimal)
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(QColor("red"))
    ed.ed.insert_image(img)
    n.save()
    note = n.repo.get(n.current)
    assert "data:image/png;base64" in note.html and note.title == "Test"
    ed.set_html(note.html)  # rechargement des images data:
    assert "data:image/png" in ed.html()
    ed._date()
    ed._hr()
    ed._checklist()
    from PySide6.QtGui import QTextTableFormat
    t = ed.ed.textCursor().insertTable(2, 2, QTextTableFormat())
    ed.ed.setTextCursor(t.cellAt(0, 0).firstCursorPosition())
    ed._table_op("row_after")
    ed._table_op("col_after")
    assert ed.ed.textCursor().currentTable().rows() == 3
    from hub.notes.editor import FindReplaceDialog, TableDialog
    from unittest.mock import patch
    with patch.object(TableDialog, "exec", return_value=True):
        ed._table()
    ed._hr()
    ed.ed.setPlainText("aa bb aa")
    d = FindReplaceDialog(ed.ed)
    d.find.setText("aa")
    d.repl.setText("cc")
    d.replace_all()
    assert ed.plain() == "cc bb cc"
    w.close()
