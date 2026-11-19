import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from hub.dashboard.view import DashboardView
from hub.notes.view import NotesView
from hub.storage import NotesRepo, TranscriptsRepo, connect
from hub.transcription.view import TranscriptionView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hub")
        self.resize(1280, 800)
        self.conn = connect()
        self.notes = NotesView(NotesRepo(self.conn))
        self.trans = TranscriptionView(TranscriptsRepo(self.conn))
        self.dash = DashboardView()
        tabs = QTabWidget()
        tabs.addTab(self.dash, "Consommation IA")
        tabs.addTab(self.notes, "Notes")
        tabs.addTab(self.trans, "Transcription")
        self.setCentralWidget(tabs)

    def closeEvent(self, e):
        self.notes.save()
        self.trans.shutdown()
        self.conn.close()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Hub")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
