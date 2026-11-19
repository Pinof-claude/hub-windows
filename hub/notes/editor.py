"""Éditeur de texte riche (QTextEdit) + barre de mise en forme."""
from __future__ import annotations

import base64
from datetime import datetime

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QImage, QKeySequence, QTextBlockFormat, QTextCharFormat,
    QTextCursor, QTextDocument, QTextFormat, QTextFrameFormat, QTextLength, QTextListFormat,
    QTextTableFormat,
)
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFontComboBox, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QPushButton, QSpinBox, QTextEdit,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72]
STYLES = ["Normal", "Titre 1", "Titre 2", "Titre 3", "Code"]
HEADING_PT = {1: 22, 2: 18, 3: 15}
MAX_IMG_WIDTH = 900


def image_to_data_url(img: QImage) -> str:
    if img.width() > MAX_IMG_WIDTH:
        img = img.scaledToWidth(MAX_IMG_WIDTH, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(ba)).decode()


class RichTextEdit(QTextEdit):
    """QTextEdit avec images collées intégrées, liens cliquables (Ctrl+clic) et cases à cocher."""

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(True)
        self.setTabChangesFocus(False)
        self.document().setDefaultFont(QFont("Segoe UI", 11))

    def insert_image(self, img: QImage) -> None:
        url = image_to_data_url(img)
        self.document().addResource(QTextDocument.ImageResource, QUrl(url), img)
        self.textCursor().insertImage(url)

    def canInsertFromMimeData(self, source):
        return source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasImage():
            img = QImage(source.imageData())
            if not img.isNull():
                self.insert_image(img)
                return
        super().insertFromMimeData(source)

    def loadResource(self, rtype, name):
        # Images intégrées en data: URL
        if rtype == QTextDocument.ImageResource and name.scheme() == "data":
            s = name.toString()
            try:
                raw = base64.b64decode(s.split(",", 1)[1])
            except (IndexError, ValueError):
                return None
            img = QImage()
            img.loadFromData(raw)
            return img
        return super().loadResource(rtype, name)

    def mouseReleaseEvent(self, e):
        cur = self.cursorForPosition(e.position().toPoint())
        anchor = self.anchorAt(e.position().toPoint())
        if anchor and e.modifiers() & Qt.ControlModifier:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(anchor))
            return
        block = cur.block()
        bf = block.blockFormat()
        if bf.marker() != QTextBlockFormat.MarkerType.NoMarker and cur.positionInBlock() == 0:
            rect = self.document().documentLayout().blockBoundingRect(block)
            x = e.position().x() + self.horizontalScrollBar().value()
            if x < rect.left() + self.document().documentMargin() + 4:
                checked = bf.marker() == QTextBlockFormat.MarkerType.Checked
                bf.setMarker(QTextBlockFormat.MarkerType.Unchecked if checked
                             else QTextBlockFormat.MarkerType.Checked)
                c = QTextCursor(block)
                c.setBlockFormat(bf)
                return
        super().mouseReleaseEvent(e)


class FindReplaceDialog(QDialog):
    def __init__(self, editor: QTextEdit, parent=None):
        super().__init__(parent)
        self.ed = editor
        self.setWindowTitle("Rechercher / remplacer")
        g = QGridLayout(self)
        self.find = QLineEdit()
        self.repl = QLineEdit()
        self.case = QCheckBox("Respecter la casse")
        self.whole = QCheckBox("Mot entier")
        self.info = QLabel()
        g.addWidget(QLabel("Rechercher"), 0, 0)
        g.addWidget(self.find, 0, 1)
        g.addWidget(QLabel("Remplacer par"), 1, 0)
        g.addWidget(self.repl, 1, 1)
        g.addWidget(self.case, 2, 0)
        g.addWidget(self.whole, 2, 1)
        row = QHBoxLayout()
        for text, fn in (("Précédent", lambda: self.do_find(True)), ("Suivant", self.do_find),
                         ("Remplacer", self.replace_one), ("Tout remplacer", self.replace_all)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        g.addLayout(row, 3, 0, 1, 2)
        g.addWidget(self.info, 4, 0, 1, 2)
        self.find.returnPressed.connect(self.do_find)

    def _flags(self, back=False):
        f = QTextDocument.FindFlag(0)
        if self.case.isChecked():
            f |= QTextDocument.FindCaseSensitively
        if self.whole.isChecked():
            f |= QTextDocument.FindWholeWords
        if back:
            f |= QTextDocument.FindBackward
        return f

    def do_find(self, back=False) -> bool:
        text = self.find.text()
        if not text:
            return False
        if self.ed.find(text, self._flags(back)):
            self.info.setText("")
            return True
        # boucle depuis le début / la fin
        c = self.ed.textCursor()
        c.movePosition(QTextCursor.End if back else QTextCursor.Start)
        self.ed.setTextCursor(c)
        ok = self.ed.find(text, self._flags(back))
        self.info.setText("" if ok else "Introuvable.")
        return ok

    def replace_one(self):
        c = self.ed.textCursor()
        sel = c.selectedText()
        same = sel == self.find.text() if self.case.isChecked() else sel.lower() == self.find.text().lower()
        if c.hasSelection() and same:
            c.insertText(self.repl.text())
        self.do_find()

    def replace_all(self):
        text = self.find.text()
        if not text:
            return
        doc = self.ed.document()
        c = QTextCursor(doc)
        c.beginEditBlock()
        n = 0
        found = doc.find(text, 0, self._flags())
        while not found.isNull():
            found.insertText(self.repl.text())
            n += 1
            found = doc.find(text, found.position(), self._flags())
        c.endEditBlock()
        self.info.setText(f"{n} remplacement(s).")


class TableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insérer un tableau")
        g = QGridLayout(self)
        self.rows = QSpinBox(minimum=1, maximum=100, value=3)
        self.cols = QSpinBox(minimum=1, maximum=20, value=3)
        g.addWidget(QLabel("Lignes"), 0, 0)
        g.addWidget(self.rows, 0, 1)
        g.addWidget(QLabel("Colonnes"), 1, 0)
        g.addWidget(self.cols, 1, 1)
        ok = QPushButton("Insérer")
        ok.clicked.connect(self.accept)
        g.addWidget(ok, 2, 0, 1, 2)


class EditorWidget(QWidget):
    """Éditeur + barres d'outils. Émet `changed` à chaque modification."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.ed = RichTextEdit()
        self.ed.textChanged.connect(self.changed)
        self.ed.currentCharFormatChanged.connect(self._sync_char)
        self.ed.cursorPositionChanged.connect(self._sync_block)
        self.ed.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ed.customContextMenuRequested.connect(self._context_menu)
        self._find_dlg = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._toolbar1())
        lay.addWidget(self._toolbar2())
        lay.addWidget(self.ed, 1)
        self.stats = QLabel()
        lay.addWidget(self.stats)
        self.ed.textChanged.connect(self._update_stats)

    # ----- helpers -----
    def _act(self, tb: QToolBar | QMenu, text: str, fn, shortcut=None, checkable=False, tip=None):
        a = QAction(text, self)
        a.setCheckable(checkable)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        a.setToolTip(f"{tip or text} ({shortcut})" if shortcut else (tip or text))
        a.triggered.connect(fn)
        tb.addAction(a)
        return a

    def _merge(self, fmt: QTextCharFormat):
        c = self.ed.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.WordUnderCursor)
        c.mergeCharFormat(fmt)
        self.ed.mergeCurrentCharFormat(fmt)
        self.ed.setFocus()

    # ----- barres -----
    def _toolbar1(self) -> QToolBar:
        tb = QToolBar()
        self._act(tb, "↶", self.ed.undo, "Ctrl+Z", tip="Annuler")
        self._act(tb, "↷", self.ed.redo, "Ctrl+Y", tip="Rétablir")
        tb.addSeparator()
        self.style_box = QComboBox()
        self.style_box.addItems(STYLES)
        self.style_box.activated.connect(lambda i: self.set_style(i))
        tb.addWidget(self.style_box)
        self.font_box = QFontComboBox()
        self.font_box.currentFontChanged.connect(self._set_family)
        tb.addWidget(self.font_box)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in SIZES])
        self.size_box.textActivated.connect(self._set_size)
        tb.addWidget(self.size_box)
        tb.addSeparator()
        self.a_bold = self._act(tb, "G", self._bold, "Ctrl+B", True, "Gras")
        self.a_italic = self._act(tb, "I", self._italic, "Ctrl+I", True, "Italique")
        self.a_under = self._act(tb, "S", self._under, "Ctrl+U", True, "Souligné")
        self.a_strike = self._act(tb, "B", self._strike, "Ctrl+Shift+X", True, "Barré")
        self.a_sup = self._act(tb, "x²", lambda: self._valign(QTextCharFormat.AlignSuperScript),
                               "Ctrl+Shift+=", True, "Exposant")
        self.a_sub = self._act(tb, "x₂", lambda: self._valign(QTextCharFormat.AlignSubScript),
                               "Ctrl+=", True, "Indice")
        for a, f in ((self.a_bold, QFont.Bold), (self.a_italic, None), (self.a_under, None)):
            fnt = a.font()
            if a is self.a_bold:
                fnt.setBold(True)
            elif a is self.a_italic:
                fnt.setItalic(True)
            else:
                fnt.setUnderline(True)
            a.setFont(fnt)
        fs = self.a_strike.font()
        fs.setStrikeOut(True)
        self.a_strike.setFont(fs)
        tb.addSeparator()
        self._act(tb, "A couleur", self._color, tip="Couleur du texte")
        self._act(tb, "Surligner", self._highlight, tip="Surlignage")
        self._act(tb, "Effacer format", self._clear_format, "Ctrl+Space",
                  tip="Effacer la mise en forme")
        return tb

    def _toolbar2(self) -> QToolBar:
        tb = QToolBar()
        self.a_left = self._act(tb, "Gauche", lambda: self._align(Qt.AlignLeft), "Ctrl+L", True)
        self.a_center = self._act(tb, "Centre", lambda: self._align(Qt.AlignHCenter), "Ctrl+E", True)
        self.a_right = self._act(tb, "Droite", lambda: self._align(Qt.AlignRight), "Ctrl+R", True)
        self.a_just = self._act(tb, "Justifié", lambda: self._align(Qt.AlignJustify), "Ctrl+J", True)
        tb.addSeparator()
        self._act(tb, "• Liste", lambda: self._list(QTextListFormat.ListDisc), "Ctrl+Shift+8",
                  tip="Liste à puces")
        self._act(tb, "1. Liste", lambda: self._list(QTextListFormat.ListDecimal), "Ctrl+Shift+7",
                  tip="Liste numérotée")
        self._act(tb, "☐ Tâches", self._checklist, "Ctrl+Shift+9", tip="Liste de tâches")
        self._act(tb, "⇤", lambda: self._indent(-1), "Ctrl+[", tip="Diminuer le retrait")
        self._act(tb, "⇥", lambda: self._indent(1), "Ctrl+]", tip="Augmenter le retrait")
        spacing = QComboBox()
        spacing.setToolTip("Interligne")
        for label in ("1.0", "1.15", "1.5", "2.0"):
            spacing.addItem(label)
        spacing.textActivated.connect(self._line_spacing)
        tb.addWidget(QLabel(" Interligne "))
        tb.addWidget(spacing)
        tb.addSeparator()
        insert = QToolButton()
        insert.setText("Insérer ▾")
        insert.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(insert)
        self._act(m, "Lien...", self._link, "Ctrl+K")
        self._act(m, "Image...", self._image)
        self._act(m, "Tableau...", self._table)
        self._act(m, "Ligne horizontale", self._hr)
        self._act(m, "Date et heure", self._date, "Ctrl+Shift+D")
        insert.setMenu(m)
        tb.addWidget(insert)
        table = QToolButton()
        table.setText("Tableau ▾")
        table.setPopupMode(QToolButton.InstantPopup)
        tm = QMenu(table)
        self._act(tm, "Ajouter ligne dessous", lambda: self._table_op("row_after"))
        self._act(tm, "Ajouter ligne dessus", lambda: self._table_op("row_before"))
        self._act(tm, "Ajouter colonne à droite", lambda: self._table_op("col_after"))
        self._act(tm, "Ajouter colonne à gauche", lambda: self._table_op("col_before"))
        self._act(tm, "Supprimer ligne", lambda: self._table_op("del_row"))
        self._act(tm, "Supprimer colonne", lambda: self._table_op("del_col"))
        table.setMenu(tm)
        tb.addWidget(table)
        tb.addSeparator()
        self._act(tb, "Rechercher", self._find, "Ctrl+F", tip="Rechercher / remplacer")
        return tb

    def _context_menu(self, pos):
        m = self.ed.createStandardContextMenu()
        m.addSeparator()
        fm = m.addMenu("Format")
        for a in (self.a_bold, self.a_italic, self.a_under, self.a_strike):
            fm.addAction(a)
        sm = m.addMenu("Style")
        for i, s in enumerate(STYLES):
            sm.addAction(s, lambda i=i: self.set_style(i))
        m.addAction("Insérer un lien...", self._link)
        m.addAction("Effacer la mise en forme", self._clear_format)
        if self.ed.textCursor().currentTable():
            tm = m.addMenu("Tableau")
            for label, op in (("Ajouter ligne dessous", "row_after"), ("Ajouter colonne à droite", "col_after"),
                              ("Supprimer ligne", "del_row"), ("Supprimer colonne", "del_col")):
                tm.addAction(label, lambda op=op: self._table_op(op))
        m.exec(self.ed.viewport().mapToGlobal(pos))

    # ----- actions caractère -----
    def _bold(self):
        f = QTextCharFormat()
        f.setFontWeight(QFont.Bold if self.a_bold.isChecked() else QFont.Normal)
        self._merge(f)

    def _italic(self):
        f = QTextCharFormat()
        f.setFontItalic(self.a_italic.isChecked())
        self._merge(f)

    def _under(self):
        f = QTextCharFormat()
        f.setFontUnderline(self.a_under.isChecked())
        self._merge(f)

    def _strike(self):
        f = QTextCharFormat()
        f.setFontStrikeOut(self.a_strike.isChecked())
        self._merge(f)

    def _valign(self, align):
        cur = self.ed.currentCharFormat().verticalAlignment()
        f = QTextCharFormat()
        f.setVerticalAlignment(QTextCharFormat.AlignNormal if cur == align else align)
        self._merge(f)

    def _set_family(self, font: QFont):
        f = QTextCharFormat()
        f.setFontFamilies([font.family()])
        self._merge(f)

    def _set_size(self, text: str):
        try:
            size = float(text.replace(",", "."))
        except ValueError:
            return
        if 1 <= size <= 400:
            f = QTextCharFormat()
            f.setFontPointSize(size)
            self._merge(f)

    def _color(self):
        col = QColorDialog.getColor(self.ed.textColor(), self, "Couleur du texte")
        if col.isValid():
            f = QTextCharFormat()
            f.setForeground(col)
            self._merge(f)

    def _highlight(self):
        col = QColorDialog.getColor(QColor("yellow"), self, "Surlignage",
                                    QColorDialog.ShowAlphaChannel)
        if col.isValid():
            f = QTextCharFormat()
            if col.alpha() == 0:
                f.setBackground(Qt.transparent)
            else:
                f.setBackground(col)
            self._merge(f)

    def _clear_format(self):
        c = self.ed.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.BlockUnderCursor)
        c.setCharFormat(QTextCharFormat())
        bf = QTextBlockFormat()
        c.setBlockFormat(bf)
        if c.currentList():
            c.currentList().remove(c.block())

    # ----- actions paragraphe -----
    def set_style(self, idx: int):
        c = self.ed.textCursor()
        c.beginEditBlock()
        bf = c.blockFormat()
        level = idx if 1 <= idx <= 3 else 0
        bf.setHeadingLevel(level)
        c.setBlockFormat(bf)
        sel = QTextCursor(c)
        sel.select(QTextCursor.BlockUnderCursor) if not c.hasSelection() else None
        f = QTextCharFormat()
        if level:
            f.setFontPointSize(HEADING_PT[level])
            f.setFontWeight(QFont.Bold)
            f.setFontFamilies([self.ed.document().defaultFont().family()])
        elif idx == 4:
            f.setFontFamilies(["Consolas", "Courier New", "monospace"])
            f.setFontFixedPitch(True)
            f.setFontPointSize(10)
            f.setFontWeight(QFont.Normal)
            f.setBackground(QColor("#f0f0f0"))
        else:
            f.setFontPointSize(self.ed.document().defaultFont().pointSizeF())
            f.setFontWeight(QFont.Normal)
            f.setFontFamilies([self.ed.document().defaultFont().family()])
            f.setFontFixedPitch(False)
            f.setBackground(Qt.transparent)
        sel.mergeCharFormat(f)
        self.ed.mergeCurrentCharFormat(f)
        c.endEditBlock()
        self.ed.setFocus()

    def _align(self, a):
        self.ed.setAlignment(a)
        self._sync_block()

    def _list(self, style):
        c = self.ed.textCursor()
        cur = c.currentList()
        if cur and cur.format().style() == style:
            for i in reversed(range(cur.count())):
                if not c.hasSelection() and cur.item(i) != c.block():
                    continue
                cur.remove(cur.item(i))
            bf = c.blockFormat()
            bf.setIndent(0)
            c.setBlockFormat(bf)
            return
        lf = QTextListFormat()
        lf.setStyle(style)
        lf.setIndent((cur.format().indent() if cur else 0) or 1)
        c.beginEditBlock()
        bf = c.blockFormat()
        bf.setMarker(QTextBlockFormat.MarkerType.NoMarker)
        c.setBlockFormat(bf)
        if cur:
            cur.setFormat(lf)
        else:
            c.createList(lf)
        c.endEditBlock()

    def _checklist(self):
        c = self.ed.textCursor()
        c.beginEditBlock()
        bf = c.blockFormat()
        if bf.marker() != QTextBlockFormat.MarkerType.NoMarker:
            bf.setMarker(QTextBlockFormat.MarkerType.NoMarker)
            c.setBlockFormat(bf)
            if c.currentList():
                c.currentList().remove(c.block())
        else:
            if not c.currentList():
                lf = QTextListFormat()
                lf.setStyle(QTextListFormat.ListDisc)
                c.createList(lf)
            bf = c.blockFormat()
            bf.setMarker(QTextBlockFormat.MarkerType.Unchecked)
            c.mergeBlockFormat(bf)
            # applique aussi aux blocs sélectionnés
            if c.hasSelection():
                doc = self.ed.document()
                b = doc.findBlock(c.selectionStart())
                end = doc.findBlock(c.selectionEnd())
                while b.isValid():
                    bc = QTextCursor(b)
                    bb = b.blockFormat()
                    bb.setMarker(QTextBlockFormat.MarkerType.Unchecked)
                    bc.setBlockFormat(bb)
                    if b == end:
                        break
                    b = b.next()
        c.endEditBlock()

    def _indent(self, delta: int):
        c = self.ed.textCursor()
        lst = c.currentList()
        if lst:
            lf = lst.format()
            lf.setIndent(max(1, lf.indent() + delta))
            lst.setFormat(lf)
        else:
            bf = c.blockFormat()
            bf.setIndent(max(0, bf.indent() + delta))
            c.setBlockFormat(bf)

    def _line_spacing(self, text: str):
        bf = QTextBlockFormat()
        bf.setLineHeight(float(text) * 100, QTextBlockFormat.ProportionalHeight.value)
        self.ed.textCursor().mergeBlockFormat(bf)

    # ----- insertions -----
    def _link(self):
        c = self.ed.textCursor()
        current = c.charFormat().anchorHref()
        url, ok = QInputDialog.getText(self, "Lien", "Adresse (URL) :", text=current or "https://")
        if not ok:
            return
        f = QTextCharFormat()
        if url.strip() and url.strip() != "https://":
            f.setAnchor(True)
            f.setAnchorHref(url.strip())
            f.setForeground(QColor("#0563c1"))
            f.setFontUnderline(True)
            if not c.hasSelection():
                c.insertText(url.strip(), f)
                return
        else:
            f.setAnchor(False)
            f.setAnchorHref("")
            f.setForeground(self.palette().text())
            f.setFontUnderline(False)
        c.mergeCharFormat(f)

    def _image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Image", "", "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        if path:
            img = QImage(path)
            if not img.isNull():
                self.ed.insert_image(img)

    def _table(self):
        d = TableDialog(self)
        if d.exec():
            tf = QTextTableFormat()
            tf.setBorder(1)
            tf.setCellPadding(4)
            tf.setCellSpacing(0)
            tf.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            tf.setWidth(QTextLength(QTextLength.PercentageLength, 100))
            self.ed.textCursor().insertTable(d.rows.value(), d.cols.value(), tf)

    def _table_op(self, op: str):
        c = self.ed.textCursor()
        t = c.currentTable()
        if not t:
            return
        cell = t.cellAt(c)
        r, col = cell.row(), cell.column()
        if op == "row_after":
            t.insertRows(r + 1, 1)
        elif op == "row_before":
            t.insertRows(r, 1)
        elif op == "col_after":
            t.insertColumns(col + 1, 1)
        elif op == "col_before":
            t.insertColumns(col, 1)
        elif op == "del_row":
            t.removeRows(r, 1)
        elif op == "del_col":
            t.removeColumns(col, 1)

    def _hr(self):
        c = self.ed.textCursor()
        c.insertBlock()
        bf = QTextBlockFormat()
        bf.setProperty(QTextFormat.BlockTrailingHorizontalRulerWidth, QTextLength(QTextLength.PercentageLength, 100))
        c.setBlockFormat(bf)
        c.insertBlock(QTextBlockFormat())

    def _date(self):
        self.ed.textCursor().insertText(datetime.now().strftime("%d/%m/%Y %H:%M"))

    def _find(self):
        if not self._find_dlg:
            self._find_dlg = FindReplaceDialog(self.ed, self)
        sel = self.ed.textCursor().selectedText()
        if sel:
            self._find_dlg.find.setText(sel)
        self._find_dlg.show()
        self._find_dlg.raise_()
        self._find_dlg.find.setFocus()

    # ----- synchro état barre -----
    def _sync_char(self, f: QTextCharFormat):
        for w in (self.font_box, self.size_box):
            w.blockSignals(True)
        fams = f.fontFamilies()
        if fams:
            self.font_box.setCurrentFont(QFont(fams[0]))
        size = f.fontPointSize() or f.font().pointSizeF()
        self.size_box.setEditText(f"{size:g}")
        for w in (self.font_box, self.size_box):
            w.blockSignals(False)
        self.a_bold.setChecked(f.fontWeight() >= QFont.Bold)
        self.a_italic.setChecked(f.fontItalic())
        self.a_under.setChecked(f.fontUnderline())
        self.a_strike.setChecked(f.fontStrikeOut())
        self.a_sup.setChecked(f.verticalAlignment() == QTextCharFormat.AlignSuperScript)
        self.a_sub.setChecked(f.verticalAlignment() == QTextCharFormat.AlignSubScript)

    def _sync_block(self):
        a = self.ed.alignment()
        self.a_left.setChecked(bool(a & Qt.AlignLeft))
        self.a_center.setChecked(bool(a & Qt.AlignHCenter))
        self.a_right.setChecked(bool(a & Qt.AlignRight))
        self.a_just.setChecked(bool(a & Qt.AlignJustify))
        lvl = self.ed.textCursor().blockFormat().headingLevel()
        self.style_box.setCurrentIndex(lvl if 1 <= lvl <= 3 else 0)

    def _update_stats(self):
        text = self.ed.toPlainText()
        self.stats.setText(f"{len(text.split())} mots · {len(text)} caractères")

    # ----- API -----
    def set_html(self, html: str):
        self.ed.blockSignals(True)
        self.ed.setHtml(html)
        self.ed.document().setModified(False)
        self.ed.blockSignals(False)
        self._update_stats()

    def html(self) -> str:
        return self.ed.toHtml()

    def plain(self) -> str:
        return self.ed.toPlainText()

