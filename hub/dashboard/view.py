from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from hub import secrets
from hub.dashboard import providers

COLS = [("input", "Entrée"), ("output", "Sortie"), ("cache_read", "Cache lu"),
        ("cache_write", "Cache écrit"), ("requests", "Requêtes")]


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


class Loader(QObject):
    done = Signal(object)  # list[(Usage|None, nom, erreur|None)]

    def __init__(self, days: int):
        super().__init__()
        self.days = days

    def run(self):
        results = []
        jobs = [("Claude Code (local)", lambda: providers.read_claude_code(self.days))]
        if k := secrets.get(secrets.ANTHROPIC):
            jobs.append(("Claude (API)", lambda k=k: providers.fetch_anthropic(k, self.days)))
        if k := secrets.get(secrets.OPENAI):
            jobs.append(("ChatGPT / OpenAI (API)", lambda k=k: providers.fetch_openai(k, self.days)))
        for name, fn in jobs:
            try:
                results.append((fn(), name, None))
            except Exception as e:  # erreur réseau / clé invalide : affichée, pas fatale
                results.append((None, name, str(e)))
        self.done.emit(results)


class UsagePanel(QWidget):
    def __init__(self, usage: providers.Usage | None, error: str | None):
        super().__init__()
        lay = QVBoxLayout(self)
        if error:
            lay.addWidget(QLabel(f"Erreur : {error}"))
            lay.addStretch()
            return
        t = usage.total()
        summary = "   ".join(f"{label} : {fmt(t.get(k, 0))}" for k, label in COLS if t.get(k))
        if usage.has_cost:
            summary += f"   Coût : {usage.total_cost():.2f} $"
        lay.addWidget(QLabel(summary or "Aucune donnée sur la période."))

        lay.addWidget(QLabel("Par modèle"))
        lay.addWidget(self._table(usage.by_model(), "Modèle"))
        lay.addWidget(QLabel("Par jour"))
        days = usage.by_day()
        for d in usage.cost_by_day:
            days.setdefault(d, {})
        lay.addWidget(self._table(dict(sorted(days.items(), reverse=True)), "Jour",
                                  usage.cost_by_day if usage.has_cost else None))

    def _table(self, rows: dict, first: str, costs: dict | None = None) -> QTableWidget:
        headers = [first] + [label for _, label in COLS] + (["Coût $"] if costs is not None else [])
        tw = QTableWidget(len(rows), len(headers))
        tw.setHorizontalHeaderLabels(headers)
        tw.verticalHeader().hide()
        tw.setEditTriggers(QTableWidget.NoEditTriggers)
        tw.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, (key, row) in enumerate(rows.items()):
            tw.setItem(i, 0, QTableWidgetItem(key))
            for j, (k, _) in enumerate(COLS, 1):
                tw.setItem(i, j, QTableWidgetItem(fmt(row.get(k, 0))))
            if costs is not None:
                tw.setItem(i, len(headers) - 1, QTableWidgetItem(f"{costs.get(key, 0):.2f}"))
        return tw


class DashboardView(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)

        keys = QGroupBox("Clés admin (stockées dans le Gestionnaire d'identification Windows)")
        form = QFormLayout(keys)
        self.ant = QLineEdit(secrets.get(secrets.ANTHROPIC))
        self.oai = QLineEdit(secrets.get(secrets.OPENAI))
        for e, ph in ((self.ant, "sk-ant-admin..."), (self.oai, "sk-admin-...")):
            e.setEchoMode(QLineEdit.Password)
            e.setPlaceholderText(ph)
        form.addRow("Anthropic", self.ant)
        form.addRow("OpenAI", self.oai)
        save = QPushButton("Enregistrer les clés")
        save.clicked.connect(self.save_keys)
        form.addRow(save)
        lay.addWidget(keys)

        bar = QHBoxLayout()
        self.period = QComboBox()
        for label, d in (("7 jours", 7), ("30 jours", 30), ("90 jours", 90)):
            self.period.addItem(label, d)
        self.period.setCurrentIndex(1)
        self.refresh_btn = QPushButton("Actualiser")
        self.refresh_btn.clicked.connect(self.refresh)
        self.status = QLabel()
        bar.addWidget(QLabel("Période :"))
        bar.addWidget(self.period)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.status, 1)
        lay.addLayout(bar)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        lay.addWidget(QLabel(
            "Limites : quotas des abonnements Claude Pro/Max et ChatGPT Plus non exposés par "
            "Anthropic/OpenAI. Coûts API = clés admin. Claude Code = lecture des logs locaux."))
        self._thread = None

    def save_keys(self):
        secrets.set(secrets.ANTHROPIC, self.ant.text())
        secrets.set(secrets.OPENAI, self.oai.text())
        self.status.setText("Clés enregistrées.")

    def refresh(self):
        if self._thread:
            return
        self.refresh_btn.setEnabled(False)
        self.status.setText("Chargement...")
        self._thread = QThread()
        self._loader = Loader(self.period.currentData())
        self._loader.moveToThread(self._thread)
        self._thread.started.connect(self._loader.run)
        self._loader.done.connect(self._show)
        self._thread.start()

    def _show(self, results):
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self.refresh_btn.setEnabled(True)
        self.status.setText("")
        self.tabs.clear()
        for usage, name, err in results:
            self.tabs.addTab(UsagePanel(usage, err), name)
