"""Safe, static AST inspector for existing PySide6 Python code.

This deliberately NEVER imports or executes a target Python module.
The v0.2 importer supports a subset of literal-property edits; it does not
promise pixel-perfect rendering or arbitrary Python source round-tripping.
"""
import ast
import difflib
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QFileDialog, QMessageBox,
    QSplitter, QComboBox, QTabWidget, QScrollArea
)
from visual_preview import ImageScraperLibraryPreview
from layout_explorer import StaticLayoutExplorer, class_methods

WIDGET_CLASSES = {
    "QWidget", "QMainWindow", "QLabel", "QPushButton", "QLineEdit",
    "QPlainTextEdit", "QTextEdit", "QTableWidget", "QTableView",
    "QListWidget", "QTabWidget", "QStackedWidget", "QSplitter", "QFrame",
    "QGroupBox", "QCheckBox", "QComboBox", "QProgressBar", "QScrollArea"
}
LAYOUT_CLASSES = {"QVBoxLayout", "QHBoxLayout", "QGridLayout", "QFormLayout"}
EDITABLE_CALLS = {
    "setFixedWidth": ("Width", 0), "setFixedHeight": ("Height", 0),
    "setMinimumWidth": ("Minimum width", 0), "setMinimumHeight": ("Minimum height", 0),
    "setMaximumWidth": ("Maximum width", 0), "setMaximumHeight": ("Maximum height", 0),
    "setSpacing": ("Spacing", 0), "setText": ("Text", 0),
    "setPlaceholderText": ("Placeholder", 0), "setWindowTitle": ("Window title", 0)
}

@dataclass
class Element:
    key: str
    cls: str
    section: str
    line: int
    methods: list

def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""

def literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
        return node.value
    return None

def analyze(source):
    """Return widgets/layouts and editable literal calls, without execution."""
    tree = ast.parse(source)
    result = []
    # Recognize user-defined widgets through direct or indirect QWidget inheritance.
    # Static analysis only: never import or execute the target module.
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    widget_types = set(WIDGET_CLASSES)
    changed = True
    while changed:
        changed = False
        for name, declaration in classes.items():
            if name not in widget_types and any(
                dotted(base).split(".")[-1] in widget_types for base in declaration.bases
            ):
                widget_types.add(name)
                changed = True
    for cl in classes.values():
        for method in (n for n in cl.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            namespace = f"{cl.name}.{method.name}"
            registry = {}
            items = []
            # Only treat direct or nested constructor assignments as declarations.
            for node in ast.walk(method):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                val = node.value
                if not isinstance(val, ast.Call):
                    continue
                kind = dotted(val.func).split(".")[-1]
                if kind not in widget_types | LAYOUT_CLASSES:
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = dotted(target)
                    if not name or name in registry:
                        continue
                    item = Element(name, kind, namespace, node.lineno, [])
                    # Qt text is often passed directly to the constructor, not setText().
                    if kind in {"QLabel", "QPushButton", "QCheckBox", "QGroupBox"} and val.args:
                        if type(literal(val.args[0])) is str:
                            item.methods.append(("Constructor text", val.args[0], "constructor"))
                    registry[name] = item
                    items.append(item)
            # Extract methods called on known instance names.
            for node in ast.walk(method):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                recv = dotted(node.func.value)
                item = registry.get(recv)
                if item is None:
                    continue
                action = node.func.attr
                if action in EDITABLE_CALLS and node.args:
                    title, index = EDITABLE_CALLS[action]
                    if len(node.args) > index and literal(node.args[index]) is not None:
                        item.methods.append((title, node.args[index], action))
                if action == "setContentsMargins" and len(node.args) == 4:
                    if all(isinstance(arg, ast.Constant) and type(arg.value) is int for arg in node.args):
                        for i, lbl in enumerate(("Margin left", "Margin top", "Margin right", "Margin bottom")):
                            item.methods.append((lbl, node.args[i], action))
                if action == "setSizes" and len(node.args) == 1 and isinstance(node.args[0], ast.List):
                    for i, value in enumerate(node.args[0].elts):
                        if type(literal(value)) is int:
                            item.methods.append((f"Splitter size {i+1}", value, action))
            result.extend(items)
    return result

def replace_literal(source, node, new_value):
    """Replace only the exact AST constant span; preserve all other bytes."""
    old = literal(node)
    if type(old) not in (str, int):
        raise ValueError("Unsupported expression")
    if type(old) is int:
        value = int(new_value)
        if value < 0 or value > 20000:
            raise ValueError("Numeric property must be 0–20000")
    else:
        value = str(new_value)
    lines = source.splitlines(keepends=True)
    if node.lineno != node.end_lineno:
        raise ValueError("Multiline constant edits are not supported")
    before = "".join(lines[:node.lineno-1])
    start = len(before) + node.col_offset
    end = len(before) + node.end_col_offset
    # AST byte offsets are UTF-8 based (Python source can include unicode).
    raw = source.encode("utf-8")
    start = len("".join(lines[:node.lineno-1]).encode("utf-8")) + node.col_offset
    end = len("".join(lines[:node.lineno-1]).encode("utf-8")) + node.end_col_offset
    return (raw[:start] + repr(value).encode("utf-8") + raw[end:]).decode("utf-8")

def library_split_sizes(source):
    """Read literal splitter sizes from ImageScraper's _library, without executing."""
    split = next((e for e in analyze(source) if e.section == "MainWindow._library" and e.key == "split" and e.cls == "QSplitter"), None)
    if split is None:
        return None
    values = {label: literal(node) for label, node, _ in split.methods if label.startswith("Splitter size ")}
    if type(values.get("Splitter size 1")) is not int or type(values.get("Splitter size 2")) is not int:
        return None
    return values["Splitter size 1"], values["Splitter size 2"]


def patch_library_split_sizes(source, first, second):
    """Change only the supported QSplitter.setSizes integer literals."""
    first, second = int(first), int(second)
    if min(first, second) < 1:
        raise ValueError("Both splitter panes must have positive sizes")
    split = next((e for e in analyze(source) if e.section == "MainWindow._library" and e.key == "split" and e.cls == "QSplitter"), None)
    if split is None:
        raise ValueError("No supported MainWindow._library splitter found")
    nodes = {label: node for label, node, _ in split.methods if label.startswith("Splitter size ")}
    if "Splitter size 1" not in nodes or "Splitter size 2" not in nodes:
        raise ValueError("Splitter sizes are not literal integers")
    edits = [(nodes["Splitter size 1"], first), (nodes["Splitter size 2"], second)]
    # Apply right-to-left, retaining valid offsets of earlier AST nodes.
    for node, value in sorted(edits, key=lambda pair: (pair[0].lineno, pair[0].col_offset), reverse=True):
        source = replace_literal(source, node, str(value))
    ast.parse(source)
    return source


class ImportInspector(QDialog):
    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        self.setWindowTitle("Python UI Import — v0.3 (visual preview + static editor)")
        self.resize(1190, 770)
        self.path = None
        self.original = ""
        self.source = ""
        self.elements = []
        self.current = None
        self.current_property = None
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        self.file_label = QLabel("No file open")
        open_btn = QPushButton("Open Python file...")
        open_btn.clicked.connect(self.choose)
        top.addWidget(open_btn)
        top.addWidget(self.file_label, 1)
        outer.addLayout(top)
        warning = QLabel("Static analysis only — target scripts are NOT executed. v0.2 edits supported source literals, not widget drag-and-drop.")
        warning.setWordWrap(True)
        outer.addWidget(warning)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Widget / Layout", "Type", "Line"])
        self.tree.setColumnWidth(0, 280)
        self.tree.currentItemChanged.connect(self.inspect)
        split.addWidget(self.tree)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.location = QLabel("Select an item to inspect its editable properties.")
        right_layout.addWidget(self.location)
        self.props = QComboBox()
        self.props.currentIndexChanged.connect(self.show_property)
        right_layout.addWidget(self.props)
        self.value = QLineEdit()
        right_layout.addWidget(self.value)
        apply_btn = QPushButton("Apply property change (in memory)")
        apply_btn.clicked.connect(self.apply_change)
        right_layout.addWidget(apply_btn)
        right_layout.addWidget(QLabel("Proposed source changes (unified diff):"))
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        right_layout.addWidget(self.diff, 1)
        split.addWidget(right)
        split.setSizes([470, 650])
        # Visual replica, source tree and diff in separate tabs.
        self.tabs = QTabWidget()
        visual_page = QWidget()
        visual_layout = QVBoxLayout(visual_page)
        visual_info = QLabel(
            "ImageScraper Actress Library (safe replica). Drag the divider then Apply. "
            "No imported source, database or scraper code is executed."
        )
        visual_info.setWordWrap(True)
        visual_layout.addWidget(visual_info)
        self.visual = ImageScraperLibraryPreview()
        self.visual.splitterChanged.connect(self.on_visual_splitter_moved)
        visual_scroll = QScrollArea()
        visual_scroll.setWidgetResizable(True)
        visual_scroll.setWidget(self.visual)
        visual_layout.addWidget(visual_scroll, 1)
        controls = QHBoxLayout()
        self.split_status = QLabel("Drag the splitter divider to change the table/gallery ratio.")
        controls.addWidget(self.split_status, 1)
        self.apply_split_button = QPushButton("Apply splitter sizes to source")
        self.apply_split_button.clicked.connect(self.apply_visual_split)
        controls.addWidget(self.apply_split_button)
        visual_layout.addLayout(controls)
        self.tabs.addTab(visual_page, "Visual Designer")
        explorer_page = QWidget()
        explorer_layout = QVBoxLayout(explorer_page)
        explorer_controls = QHBoxLayout()
        explorer_controls.addWidget(QLabel("Source method:"))
        self.method_picker = QComboBox()
        self.method_picker.currentTextChanged.connect(self.show_method_preview)
        explorer_controls.addWidget(self.method_picker, 1)
        explorer_layout.addLayout(explorer_controls)
        explorer_help = QLabel(
            "Static layout approximation — click an item to select its declaration. "
            "Edit supported properties in Widget Tree. Dragging arbitrary layout-managed "
            "widgets is not yet supported."
        )
        explorer_help.setWordWrap(True)
        explorer_layout.addWidget(explorer_help)
        self.explorer = StaticLayoutExplorer()
        self.explorer.widgetSelected.connect(self.select_source_widget)
        explorer_scroll = QScrollArea()
        explorer_scroll.setWidgetResizable(True)
        explorer_scroll.setWidget(self.explorer)
        explorer_layout.addWidget(explorer_scroll, 1)
        self.tabs.addTab(explorer_page, "Layout Explorer")
        self.tabs.addTab(split, "Widget Tree")
        diff_page = QWidget()
        diff_layout = QVBoxLayout(diff_page)
        right_layout.removeWidget(self.diff)
        self.diff.setParent(diff_page)
        diff_layout.addWidget(QLabel("Unified diff: original versus modified Python source"))
        diff_layout.addWidget(self.diff, 1)
        self.tabs.addTab(diff_page, "Source Changes")
        outer.addWidget(self.tabs, 1)
        bottom = QHBoxLayout()
        self.count = QLabel()
        bottom.addWidget(self.count, 1)
        reset = QPushButton("Discard edits")
        reset.clicked.connect(self.reset)
        save = QPushButton("Save as copy...")
        save.clicked.connect(self.save_copy)
        bottom.addWidget(reset)
        bottom.addWidget(save)
        outer.addLayout(bottom)
        if path:
            self.load(path)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open existing PySide6 source", "", "Python files (*.py)")
        if path:
            self.load(path)

    def load(self, path):
        try:
            source = Path(path).read_text(encoding="utf-8-sig")
            ast.parse(source)
        except (OSError, UnicodeError, SyntaxError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.path = Path(path)
        self.original = source
        self.source = source
        self.file_label.setText(str(self.path))
        self.reload_view()

    def reload_view(self, selected_key=None):
        self.elements = analyze(self.source)
        self.tree.blockSignals(True)
        self.tree.clear()
        sections = {}
        selected = None
        for element in self.elements:
            section = sections.get(element.section)
            if section is None:
                section = QTreeWidgetItem([element.section, "Method", ""])
                sections[element.section] = section
                self.tree.addTopLevelItem(section)
            item = QTreeWidgetItem([element.key, element.cls, str(element.line)])
            item.setData(0, Qt.ItemDataRole.UserRole, element)
            section.addChild(item)
            if (element.section, element.key) == selected_key:
                selected = item
        self.tree.expandAll()
        self.tree.blockSignals(False)
        previous = self.method_picker.currentText()
        self.method_picker.blockSignals(True)
        self.method_picker.clear()
        names = list(class_methods(self.source))
        self.method_picker.addItems([section for section in names if any(e.section == section for e in self.elements)])
        if previous in [self.method_picker.itemText(i) for i in range(self.method_picker.count())]:
            self.method_picker.setCurrentText(previous)
        elif "MainWindow._library" in names:
            self.method_picker.setCurrentText("MainWindow._library")
        self.method_picker.blockSignals(False)
        self.show_method_preview(self.method_picker.currentText())
        self.count.setText(f"{len(self.elements)} declared widgets/layouts, {sum(len(e.methods) for e in self.elements)} editable literal properties")
        self.update_diff()
        sizes = library_split_sizes(self.source)
        supported = sizes is not None
        self.tabs.setTabEnabled(0, supported)
        self.apply_split_button.setEnabled(supported)
        if supported:
            self.visual.set_split_sizes(sizes)
            self.split_status.setText(f"Source splitter sizes: {sizes[0]} / {sizes[1]} — drag divider to change")
        elif self.tabs.currentIndex() == 0:
            self.tabs.setCurrentIndex(1)
        self.tree.setCurrentItem(selected)

    def show_method_preview(self, method):
        if method:
            try:
                self.explorer.render(self.source, method, self.elements)
            except (TypeError, ValueError, RuntimeError) as exc:
                self.split_status.setText(f"Layout Explorer: unsupported source construct ({exc})")

    def select_source_widget(self, section, key):
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            if group.text(0) != section:
                continue
            for j in range(group.childCount()):
                item = group.child(j)
                if item.text(0) == key:
                    self.tree.setCurrentItem(item)
                    self.tabs.setCurrentIndex(2)
                    return

    def on_visual_splitter_moved(self, left, right):
        self.split_status.setText(f"Preview sizes: {left} / {right} — click Apply to update Python")
        self.apply_split_button.setEnabled(True)

    def apply_visual_split(self):
        if library_split_sizes(self.source) is None:
            QMessageBox.warning(self, "Unsupported layout", "No editable ImageScraper splitter found.")
            return
        left, right = self.visual.current_split_sizes()
        try:
            self.source = patch_library_split_sizes(self.source, left, right)
        except (ValueError, SyntaxError) as exc:
            QMessageBox.warning(self, "Unable to edit splitter", str(exc))
            return
        self.reload_view()
        self.tabs.setCurrentIndex(3)

    def inspect(self, item, _previous):
        self.current = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.props.blockSignals(True)
        self.props.clear()
        if self.current:
            e = self.current
            self.location.setText(f"{e.section}  •  {e.key}: {e.cls}  •  line {e.line}")
            for label, node, action in e.methods:
                self.props.addItem(f"{label}  (line {node.lineno})", (label, node, action))
        else:
            self.location.setText("Select a widget or layout to inspect.")
        self.props.blockSignals(False)
        self.show_property(self.props.currentIndex())

    def show_property(self, index):
        entry = self.props.itemData(index) if index >= 0 else None
        self.current_property = entry
        self.value.setEnabled(entry is not None)
        self.value.setText(str(literal(entry[1])) if entry else "")

    def apply_change(self):
        if not self.current or not self.current_property:
            return
        label, node, _ = self.current_property
        selected_key = (self.current.section, self.current.key)
        try:
            updated = replace_literal(self.source, node, self.value.text())
            ast.parse(updated)
        except (ValueError, SyntaxError, UnicodeError) as exc:
            QMessageBox.warning(self, "Property edit failed", str(exc))
            return
        self.source = updated
        self.reload_view(selected_key)

    def update_diff(self):
        diff = difflib.unified_diff(
            self.original.splitlines(), self.source.splitlines(),
            fromfile=str(self.path) + " (original)" if self.path else "original",
            tofile="modified copy", lineterm=""
        )
        value = "\n".join(diff)
        self.diff.setPlainText(value if value else "No pending changes")

    def reset(self):
        self.source = self.original
        self.reload_view()

    def save_copy(self):
        if self.path is None:
            return
        suggested = self.path.with_name(self.path.stem + "_director_edit.py")
        path, _ = QFileDialog.getSaveFileName(self, "Save edited Python as copy", str(suggested), "Python files (*.py)")
        if not path:
            return
        destination = Path(path)
        if destination.resolve() == self.path.resolve():
            QMessageBox.warning(self, "Original protected", "Choose a different filename. v0.2 never overwrites the source.")
            return
        try:
            ast.parse(self.source)
            destination.write_text(self.source, encoding="utf-8")
        except (OSError, UnicodeError, SyntaxError) as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        QMessageBox.information(self, "Saved", f"Edited copy saved to:\n{destination}")
