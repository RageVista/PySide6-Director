"""Static layout explorer: render safe Qt approximations from Python AST.

The target script is never imported, evaluated or executed. This intentionally
supports a useful subset of Qt layout calls rather than claiming fidelity for
dynamic methods, conditions, custom painting, or application data.
"""
import ast

from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QSplitter,
    QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit, QCheckBox,
    QComboBox, QTableWidget, QListWidget, QTabWidget, QStackedWidget,
    QFrame, QGroupBox, QProgressBar, QScrollArea, QSizePolicy
)

LAYOUT_TYPES = {"QVBoxLayout", "QHBoxLayout", "QGridLayout", "QFormLayout"}
CONTAINER_TYPES = {"QSplitter", "QTabWidget", "QStackedWidget"}
SKIPPED_ROOTS = {"QWidget", "QFrame", "QMainWindow", "QGroupBox"}


def path(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = path(node.value)
        return f"{prefix}.{node.attr}" if prefix else ""
    return ""


def scalar(node, default=None):
    if isinstance(node, ast.Constant) and type(node.value) in (str, int, float, bool):
        return node.value
    return default


def class_methods(source):
    """Mapping of names to actual class methods, with no target execution."""
    tree = ast.parse(source)
    return {
        f"{cls.name}.{method.name}": method
        for cls in tree.body if isinstance(cls, ast.ClassDef)
        for method in cls.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def ordered_calls(method):
    """Calls sorted by source location (not execution order)."""
    return sorted(
        (n for n in ast.walk(method) if isinstance(n, ast.Call)),
        key=lambda n: (n.lineno, n.col_offset)
    )


class StaticLayoutExplorer(QWidget):
    widgetSelected = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._section = ""
        self._objects = {}
        self._layouts = {}
        self._object_keys = {}
        self._selected = None
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(10, 10, 10, 10)

    def _clear(self):
        while self._root.count():
            item = self._root.takeAt(0)
            obj = item.widget()
            if obj is not None:
                obj.deleteLater()
            elif item.layout() is not None:
                self._delete_layout(item.layout())
        self._objects = {}
        self._layouts = {}
        self._object_keys = {}
        self._selected = None

    def _delete_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._delete_layout(item.layout())
        layout.deleteLater()

    def render(self, source, section, elements):
        self._clear()
        self._section = section
        method = class_methods(source).get(section)
        if method is None:
            self._root.addWidget(QLabel("Choose an imported class method."))
            return

        entries = [e for e in elements if e.section == section]
        for element in entries:
            if element.cls in LAYOUT_TYPES:
                self._layouts[element.key] = self._make_layout(element.cls)
            else:
                widget = self._make_widget(element.cls, element.key)
                self._objects[element.key] = widget
                self._object_keys[id(widget)] = element.key
                widget.installEventFilter(self)
                widget.setToolTip(f"{element.key}: {element.cls} — click to select")
                widget.setObjectName("staticPreview_" + element.key.replace(".", "_"))

        # Constructors with a QWidget argument establish layout ownership,
        # for example: dl = QVBoxLayout(detail).
        owner_of = {}
        for node in ast.walk(method):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
                continue
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                key = path(target)
                if key in self._layouts and value.args:
                    owner = path(value.args[0])
                    if owner in self._objects and owner not in owner_of:
                        owner_of[owner] = key

        child_keys = set()
        for owner, layout_key in owner_of.items():
            container = self._objects[owner]
            layout = self._layouts[layout_key]
            if container.layout() is None:
                container.setLayout(layout)
                child_keys.add(layout_key)

        # Reconstruct supported calls in source order, with each child assigned once.
        for call in ordered_calls(method):
            if not isinstance(call.func, ast.Attribute):
                continue
            key, action = path(call.func.value), call.func.attr
            args = call.args
            if key in self._layouts:
                parent = self._layouts[key]
                if action in ("addWidget", "insertWidget") and args:
                    idx = 1 if action == "insertWidget" else 0
                    if len(args) > idx:
                        child = path(args[idx])
                        if child in self._objects and child not in child_keys:
                            self._add_layout_widget(parent, self._objects[child], args[idx+1:])
                            child_keys.add(child)
                elif action in ("addLayout", "insertLayout") and args:
                    idx = 1 if action == "insertLayout" else 0
                    if len(args) > idx:
                        child = path(args[idx])
                        if child in self._layouts and child not in child_keys and child != key:
                            self._add_layout_child(parent, self._layouts[child], args[idx+1:])
                            child_keys.add(child)
                elif action == "setSpacing" and args:
                    space = scalar(args[0])
                    if type(space) is int:
                        parent.setSpacing(max(0, min(150, space)))
                elif action == "setContentsMargins" and len(args) >= 4:
                    margins = [scalar(x) for x in args[:4]]
                    if all(type(x) is int for x in margins):
                        parent.setContentsMargins(*[max(0, min(150, v)) for v in margins])
            elif key in self._objects:
                parent = self._objects[key]
                if action in ("addWidget", "addTab") and args:
                    child = path(args[0])
                    if child in self._objects and child not in child_keys:
                        if isinstance(parent, QTabWidget) and action == "addTab":
                            title = scalar(args[1], child) if len(args) > 1 else child
                            parent.addTab(self._objects[child], str(title))
                            child_keys.add(child)
                        elif isinstance(parent, (QSplitter, QStackedWidget)) and action == "addWidget":
                            parent.addWidget(self._objects[child])
                            child_keys.add(child)
                elif action == "setCurrentIndex" and args:
                    index = scalar(args[0])
                    if type(index) is int and hasattr(parent, "setCurrentIndex"):
                        parent.setCurrentIndex(index)
                elif action in ("setFixedWidth", "setFixedHeight", "setMinimumWidth",
                                "setMinimumHeight", "setMaximumHeight", "setMaximumWidth") and args:
                    n = scalar(args[0])
                    if type(n) is int and 0 <= n <= 2000:
                        getattr(parent, action)(n)
                elif action in ("setText", "setPlaceholderText") and args:
                    val = scalar(args[0])
                    if isinstance(val, str) and hasattr(parent, action):
                        getattr(parent, action)(val)

        # Put surviving top-level layouts and stand-alone widgets in a vertical page.
        # Layouts with owners are contained by their owning widget.
        used = set(child_keys)
        roots = [(e.key, self._layouts[e.key]) for e in entries
                 if e.key in self._layouts and e.key not in used]
        if roots:
            for key, layout in roots:
                wrapper = QFrame()
                wrapper.setFrameShape(QFrame.Shape.StyledPanel)
                wrap = QVBoxLayout(wrapper)
                wrap.setContentsMargins(7, 7, 7, 7)
                wrap.addWidget(QLabel(f"{key}  ·  {next(e.cls for e in entries if e.key == key)}"))
                wrap.addLayout(layout)
                self._root.addWidget(wrapper)
        for e in entries:
            if e.key in self._objects and e.key not in used:
                if e.cls in SKIPPED_ROOTS and roots:
                    # Root panels are often incomplete without external builder context.
                    continue
                self._root.addWidget(self._objects[e.key])
        self._root.addStretch(1)
        if not entries:
            self._root.addWidget(QLabel("No static widget declarations found in this method."))

    def _make_layout(self, kind):
        return {
            "QVBoxLayout": QVBoxLayout, "QHBoxLayout": QHBoxLayout,
            "QGridLayout": QGridLayout, "QFormLayout": QFormLayout,
        }[kind]()

    def _add_layout_widget(self, layout, widget, extra):
        if isinstance(layout, QGridLayout):
            ints = [scalar(x) for x in extra[:4]]
            row = ints[0] if len(ints) > 0 else 0
            col = ints[1] if len(ints) > 1 else 0
            if type(row) is int and type(col) is int:
                try:
                    layout.addWidget(widget, max(0,row), max(0,col))
                except (TypeError, RuntimeError):
                    pass
        elif isinstance(layout, QFormLayout):
            layout.addRow(widget)
        else:
            layout.addWidget(widget)

    def _add_layout_child(self, parent, child, extra):
        if isinstance(parent, QGridLayout):
            nums = [scalar(x) for x in extra]
            if len(nums) >= 2 and all(type(x) is int for x in nums[:2]):
                parent.addLayout(child, max(0,nums[0]), max(0,nums[1]))
            else:
                parent.addLayout(child, parent.rowCount(), 0)
        elif isinstance(parent, QFormLayout):
            parent.addRow(child)
        else:
            parent.addLayout(child)

    def _make_widget(self, kind, key):
        name = key.replace("self.", "")
        if kind == "QLabel":
            return QLabel(name)
        if kind == "QPushButton":
            button = QPushButton(name)
            button.setCheckable(False)
            return button
        if kind == "QLineEdit":
            return QLineEdit()
        if kind == "QTextEdit":
            return QTextEdit()
        if kind == "QPlainTextEdit":
            return QPlainTextEdit()
        if kind == "QCheckBox":
            return QCheckBox(name)
        if kind == "QComboBox":
            return QComboBox()
        if kind == "QTableWidget" or kind == "QTableView":
            table = QTableWidget(2, 3)
            table.setHorizontalHeaderLabels(["Column 1", "Column 2", "Column 3"])
            table.setMinimumSize(160, 130)
            return table
        if kind == "QListWidget":
            listbox = QListWidget()
            listbox.addItem("Placeholder item")
            return listbox
        if kind == "QTabWidget":
            return QTabWidget()
        if kind == "QStackedWidget":
            return QStackedWidget()
        if kind == "QSplitter":
            widget = QSplitter(Qt.Orientation.Horizontal)
            widget.setChildrenCollapsible(False)
            return widget
        if kind == "QFrame":
            widget = QFrame()
            widget.setFrameShape(QFrame.Shape.StyledPanel)
            return widget
        if kind == "QGroupBox":
            return QGroupBox(name)
        if kind == "QProgressBar":
            return QProgressBar()
        if kind == "QScrollArea":
            return QScrollArea()
        if kind in ("QWidget", "QMainWindow"):
            return QWidget()
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        box = QVBoxLayout(panel)
        box.addWidget(QLabel(f"{kind} (custom widget preview)"))
        return panel

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            key = self._object_keys.get(id(obj))
            if key is not None:
                self.widgetSelected.emit(self._section, key)
                return True
        return super().eventFilter(obj, event)
