"""PySide6 Director MVP: visual editing, JSON persistence and Python export."""
import json
import sys
from python_importer import ImportInspector
from pathlib import Path
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QLineEdit, QTextEdit,
    QCheckBox, QComboBox, QScrollArea, QSpinBox, QFileDialog, QMessageBox,
    QDialog, QDialogButtonBox, QGroupBox
)

CANVAS_W, CANVAS_H = 900, 600
KINDS = ['QLabel', 'QPushButton', 'QLineEdit', 'QTextEdit', 'QCheckBox', 'QComboBox', 'Image']
DEFAULTS = {
    'QLabel': ('Label', 130, 35), 'QPushButton': ('Button', 130, 38),
    'QLineEdit': ('Enter text...', 190, 36), 'QTextEdit': ('Text area', 210, 100),
    'QCheckBox': ('Check me', 145, 35), 'QComboBox': ('Option 1,Option 2', 170, 36),
    'Image': ('', 200, 140)
}

def make_widget(data, parent):
    kind, value = data['kind'], data.get('text', '')
    if kind == 'QLabel': w = QLabel(value, parent)
    elif kind == 'QPushButton': w = QPushButton(value, parent)
    elif kind == 'QLineEdit': w = QLineEdit(parent); w.setPlaceholderText(value)
    elif kind == 'QTextEdit': w = QTextEdit(parent); w.setPlainText(value)
    elif kind == 'QCheckBox': w = QCheckBox(value, parent)
    elif kind == 'QComboBox': w = QComboBox(parent); w.addItems([s.strip() for s in value.split(',') if s.strip()])
    else:
        w = QLabel('Image preview', parent)
        w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = data.get('image', '')
        if path and Path(path).is_file():
            pic = QPixmap(path)
            if not pic.isNull(): w.setPixmap(pic.scaled(data['w'], data['h'], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    w.setObjectName(data['name'])
    w.setGeometry(data['x'], data['y'], data['w'], data['h'])
    return w

class DesignItem(QWidget):
    changed = Signal()
    selected = Signal(object)
    def __init__(self, data, parent):
        super().__init__(parent)
        self.data = data
        self.drag_origin = None
        self.start_rect = None
        self.resizing = False
        self.active = False
        self.inner = make_widget(data, self)
        self.inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(data['x'], data['y'], data['w'], data['h'])
        self.inner.setGeometry(0, 0, self.width(), self.height())
        self._style()
    def _style(self):
        self.setStyleSheet('DesignItem { border: 2px solid #2980d9; background: transparent; }' if self.active else 'DesignItem { border: 1px dashed #9ca3af; background: transparent; }')
    def select(self, active): self.active = active; self._style(); self.update()
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton: return
        self.selected.emit(self)
        self.drag_origin = event.globalPosition().toPoint()
        self.start_rect = self.geometry()
        self.resizing = event.position().x() >= self.width()-15 and event.position().y() >= self.height()-15
        event.accept()
    def mouseMoveEvent(self, event):
        if self.drag_origin is None: return
        delta = event.globalPosition().toPoint() - self.drag_origin
        rect = QRect(self.start_rect)
        if self.resizing:
            rect.setWidth(max(35, min(CANVAS_W-rect.x(), rect.width()+delta.x())))
            rect.setHeight(max(24, min(CANVAS_H-rect.y(), rect.height()+delta.y())))
        else:
            rect.moveTo(max(0, min(CANVAS_W-rect.width(), rect.x()+delta.x())), max(0, min(CANVAS_H-rect.height(), rect.y()+delta.y())))
        self.setGeometry(rect)
        self.inner.setGeometry(0, 0, rect.width(), rect.height())
        event.accept()
    def mouseReleaseEvent(self, event):
        if self.drag_origin is None: return
        g = self.geometry()
        self.data.update(x=g.x(), y=g.y(), w=g.width(), h=g.height())
        self.drag_origin = None
        self.changed.emit()
        event.accept()
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.active:
            from PySide6.QtGui import QPainter, QColor
            p = QPainter(self)
            p.fillRect(self.width()-11, self.height()-11, 10, 10, QColor('#2980d9'))

class Director(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PySide6 Director — v0.3')
        self.resize(1380, 850)
        self.path = None
        self.items = []
        self.current = None
        self.counter = 0
        self._building_properties = False
        root = QWidget(); self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        left = QGroupBox('Widget toolbox'); left.setFixedWidth(185)
        lb = QVBoxLayout(left)
        for kind in KINDS:
            btn = QPushButton('+ ' + kind); btn.clicked.connect(lambda _, k=kind: self.add_item(k)); lb.addWidget(btn)
        lb.addStretch()
        layout.addWidget(left)
        scroll = QScrollArea(); scroll.setWidgetResizable(False)
        self.canvas = QWidget(); self.canvas.setFixedSize(CANVAS_W, CANVAS_H)
        self.canvas.setStyleSheet('background: #f7f8fb;')
        scroll.setWidget(self.canvas); layout.addWidget(scroll, 1)
        right = QGroupBox('Selected widget properties'); right.setFixedWidth(285)
        self.properties = QFormLayout(right)
        self.prop = {}
        for key, label in [('name','Object name'),('text','Text / options'),('image','Image path')]:
            edit = QLineEdit(); edit.editingFinished.connect(self.apply_properties)
            self.properties.addRow(label, edit); self.prop[key] = edit
        for key, label in [('x','X'),('y','Y'),('w','Width'),('h','Height')]:
            edit = QSpinBox(); edit.setRange(0 if key in ('x','y') else 20, 2000)
            edit.valueChanged.connect(lambda _v: self.apply_properties())
            self.properties.addRow(label, edit); self.prop[key] = edit
        choose = QPushButton('Browse image...'); choose.clicked.connect(self.choose_image)
        self.properties.addRow(choose)
        remove = QPushButton('Delete selected'); remove.clicked.connect(self.delete_selected)
        self.properties.addRow(remove)
        self.properties.addRow(QLabel('Drag widgets to move.\nDrag bottom-right corner to resize.'))
        layout.addWidget(right)
        menu = self.menuBar().addMenu('File')
        for label, handler, shortcut in [
            ('New design',self.new_design,'Ctrl+N'),('Open design JSON',self.open_json,'Ctrl+O'),
            ('Save design JSON',self.save_json,'Ctrl+S'),('Export Python',self.export_python,'Ctrl+E'),
            ('Preview runtime',self.preview,'F5')]:
            a = QAction(label,self); a.setShortcut(shortcut); a.triggered.connect(handler); menu.addAction(a)
        import_menu = self.menuBar().addMenu('Import')
        import_action = QAction('Inspect existing Python UI...', self)
        import_action.setShortcut('Ctrl+I')
        import_action.triggered.connect(self.import_python)
        import_menu.addAction(import_action)
        self.statusBar().showMessage('Ready — create widgets from toolbox; save JSON to keep editing')
        self.select_item(None)
    def select_item(self, item):
        self.current = item
        for each in self.items: each.select(each is item)
        self._building_properties = True
        for key, control in self.prop.items():
            control.setEnabled(item is not None)
            if isinstance(control, QSpinBox): control.setValue(item.data.get(key,0) if item else 0)
            else: control.setText(str(item.data.get(key,'')) if item else '')
        self._building_properties = False
    def add_item(self, kind, data=None):
        if data is None:
            text, w, h = DEFAULTS[kind]
            self.counter += 1
            data = {'kind':kind,'name':f'{kind.lower().replace("q", "", 1)}_{self.counter}',
                    'text':text,'x':30+(self.counter*23)%400,'y':35+(self.counter*23)%300,
                    'w':w,'h':h,'image':''}
        item = DesignItem(data,self.canvas)
        item.selected.connect(self.select_item)
        item.changed.connect(lambda: self.select_item(item))
        item.show(); self.items.append(item); self.select_item(item)
    def apply_properties(self):
        if self._building_properties or not self.current: return
        item = self.current
        for key, control in self.prop.items(): item.data[key] = control.value() if isinstance(control,QSpinBox) else control.text()
        item.data['w'] = max(20,item.data['w']); item.data['h'] = max(20,item.data['h'])
        item.data['x'] = min(item.data['x'], CANVAS_W-item.data['w'])
        item.data['y'] = min(item.data['y'], CANVAS_H-item.data['h'])
        fresh = make_widget(item.data,item)
        item.inner.deleteLater(); item.inner = fresh
        item.setGeometry(item.data['x'],item.data['y'],item.data['w'],item.data['h'])
        fresh.setGeometry(0,0,item.width(),item.height()); fresh.show(); item.update()
    def import_python(self):
        dialog = ImportInspector(self)
        dialog.exec()

    def choose_image(self):
        if not self.current: return
        path, _ = QFileDialog.getOpenFileName(self,'Choose image','','Images (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path: self.prop['image'].setText(path); self.apply_properties()
    def delete_selected(self):
        if not self.current: return
        item=self.current; self.items.remove(item); self.select_item(None); item.deleteLater()
    def new_design(self):
        for item in self.items: item.deleteLater()
        self.items.clear(); self.select_item(None); self.path = None; self.counter=0
    def open_json(self):
        path,_ = QFileDialog.getOpenFileName(self,'Open Director design','','Director JSON (*.json)')
        if not path: return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            if data.get('format') != 'pyside6-director-v1': raise ValueError('Unsupported design format')
            for obj in data['widgets']:
                if obj.get('kind') not in KINDS: raise ValueError('Unknown widget kind')
            self.new_design()
            for obj in data['widgets']: self.add_item(obj['kind'],obj)
            self.counter=len(self.items); self.path=path
        except (ValueError,KeyError,OSError,TypeError) as exc: QMessageBox.critical(self,'Open failed',str(exc))
    def save_json(self):
        path=self.path
        if not path: path,_=QFileDialog.getSaveFileName(self,'Save Director design','design.json','Director JSON (*.json)')
        if not path: return
        try:
            Path(path).write_text(json.dumps({'format':'pyside6-director-v1','canvas':[CANVAS_W,CANVAS_H],
                'widgets':[dict(item.data) for item in self.items]},indent=2),encoding='utf-8')
            self.path=path; self.statusBar().showMessage('Saved '+path)
        except OSError as exc: QMessageBox.critical(self,'Save failed',str(exc))
    def export_python(self):
        path,_=QFileDialog.getSaveFileName(self,'Export runnable Python','generated_ui.py','Python (*.py)')
        if not path: return
        lines=[
            '"""Generated by PySide6 Director. Edit the JSON source to regenerate."""',
            'import sys', 'from pathlib import Path',
            'from PySide6.QtCore import Qt', 'from PySide6.QtGui import QPixmap',
            'from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QLineEdit, QTextEdit, QCheckBox, QComboBox',
            '', 'class GeneratedWindow(QWidget):', '    def __init__(self):',
            '        super().__init__()', "        self.setWindowTitle('Generated PySide6 UI')",
            f'        self.resize({CANVAS_W}, {CANVAS_H})'
        ]
        for idx,item in enumerate(self.items):
            d=item.data; k=d['kind']; name='widget_'+str(idx); t=repr(d.get('text',''))
            if k=='Image':
                lines += [f'        self.{name} = QLabel(self)',f"        self.{name}.setText('Image preview')",f'        self.{name}.setAlignment(Qt.AlignmentFlag.AlignCenter)']
                path_repr=repr(d.get('image',''))
                lines += [f'        image_path = {path_repr}', '        if image_path and Path(image_path).is_file():',
                          '            pixmap = QPixmap(image_path)', '            if not pixmap.isNull():',
                          f'                self.{name}.setPixmap(pixmap.scaled({d["w"]}, {d["h"]}, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))']
            elif k=='QComboBox':
                lines += [f'        self.{name} = QComboBox(self)',f'        self.{name}.addItems([s.strip() for s in {t}.split(",") if s.strip()])']
            elif k=='QLineEdit':
                lines += [f'        self.{name} = QLineEdit(self)',f'        self.{name}.setPlaceholderText({t})']
            elif k=='QTextEdit':
                lines += [f'        self.{name} = QTextEdit(self)',f'        self.{name}.setPlainText({t})']
            else:
                lines += [f'        self.{name} = {k}({t}, self)']
            lines += [f'        self.{name}.setObjectName({d["name"]!r})',
                      f'        self.{name}.setGeometry({d["x"]}, {d["y"]}, {d["w"]}, {d["h"]})']
        lines += ['',"if __name__ == '__main__':",'    app = QApplication(sys.argv)',
                  '    window = GeneratedWindow()', '    window.show()', '    sys.exit(app.exec())','']
        try: Path(path).write_text('\n'.join(lines),encoding='utf-8'); self.statusBar().showMessage('Exported '+path)
        except OSError as exc: QMessageBox.critical(self,'Export failed',str(exc))
    def preview(self):
        dialog=QDialog(self); dialog.setWindowTitle('Runtime preview'); dialog.resize(CANVAS_W,CANVAS_H)
        for item in self.items:
            w=make_widget(item.data,dialog); w.show()
        dialog.exec()

if __name__ == '__main__':
    app=QApplication(sys.argv)
    window=Director(); window.show()
    sys.exit(app.exec())
