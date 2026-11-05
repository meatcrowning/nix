"""Native per-sample rows; reducing the count keeps draft rows until reloaded."""
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QGroupBox, QPlainTextEdit, QSpinBox


class SampleEditor(QWidget):
    changed = Signal()

    def __init__(self, entries):
        super().__init__()
        self.rows = []
        self.count = 0
        self.explicit = False
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.set_entries(entries)

    def set_entries(self, entries):
        with QSignalBlocker(self):
            for group, *_ in self.rows:
                self.layout.removeWidget(group)
                group.deleteLater()
            self.rows = []
            for entry in entries:
                self.add_row(entry)
            self.set_count(len(entries))

    def add_row(self, entry):
        group = QGroupBox(f'Sample {len(self.rows) + 1}')
        form = QFormLayout(group)
        prompt = QPlainTextEdit(entry['prompt'])
        prompt.setMaximumHeight(90)
        prompt.setPlaceholderText('Prompt for this sample')
        seed = QSpinBox()
        seed.setRange(0, 2147483647)
        seed.setValue(entry['seed'])
        form.addRow('Prompt', prompt)
        form.addRow('Seed', seed)
        form.setRowVisible(seed, self.explicit)
        prompt.textChanged.connect(self.changed)
        seed.valueChanged.connect(lambda *_: self.changed.emit())
        self.rows.append((group, prompt, seed, form))
        self.layout.addWidget(group)

    def set_count(self, count):
        while len(self.rows) < count:
            previous = self.rows[-1] if self.rows else None
            self.add_row({'prompt': previous[1].toPlainText() if previous else '',
                          'seed': (previous[2].value() + 1) % 2147483648 if previous else 42})
        self.count = count
        for i, (group, *_) in enumerate(self.rows):
            group.setVisible(i < count)
        self.changed.emit()

    def set_explicit(self, explicit):
        self.explicit = explicit
        for _, _, seed, form in self.rows:
            form.setRowVisible(seed, explicit)

    def entries(self):
        return [{'prompt': prompt.toPlainText(), 'seed': seed.value()}
                for _, prompt, seed, _ in self.rows[:self.count]]
