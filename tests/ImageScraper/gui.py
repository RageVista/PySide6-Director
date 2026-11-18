"""ImageScraper desktop shell. Site-specific scraping belongs in scrapers/."""
from pathlib import Path
import traceback
from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal, Slot, QUrl, QBuffer, QIODevice, QByteArray
from PySide6.QtGui import QDesktopServices, QPixmap, QMovie
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QFileDialog, QTabWidget
)
from .db import Database
from .image_downloads import download_images
from scrapers.example import ExampleScraper
from scrapers.famousboard import FamousBoardScraper

STYLE = """
QMainWindow, QWidget { background: #151b24; color: #e7ecf4; font-size: 13px; }
QFrame#sidebar { background: #10151d; border-right: 1px solid #313b4b; }
QFrame#panel, QGroupBox { background: #1e2632; border: 1px solid #344153; border-radius: 9px; }
QGroupBox { margin-top: 12px; padding: 14px 9px 9px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 13px; padding: 0 5px; }
QLineEdit, QPlainTextEdit, QTableWidget, QListWidget { background: #111822; border: 1px solid #354357; border-radius: 5px; padding: 7px; color: #e7ecf4; }
QPushButton { background: #2b3a4c; border: 1px solid #41546b; border-radius: 6px; padding: 9px 12px; font-weight: 500; }
QPushButton:hover { background: #38506b; } QPushButton:disabled { color: #7d8899; background: #202b38; }
QPushButton#primary { background: #176eae; border-color: #268ac9; }
QPushButton#primary:hover { background: #2186cc; }
QPushButton#nav { text-align: left; border: none; background: transparent; padding: 13px; }
QPushButton#nav:checked { background: #24394f; border-left: 3px solid #58aaff; }
QHeaderView::section { background: #253144; color: #dbe6f6; border: none; padding: 8px; }
QTabWidget::pane { border: 1px solid #354357; } QTabBar::tab { background: #1d2633; padding: 9px 13px; }
QTabBar::tab:selected { background: #304761; }
QStatusBar { background: #10151d; }
"""

class WorkerSignals(QObject):
    done = Signal(int, str)
    failed = Signal(str)
    preview_done = Signal(object)
    download_done = Signal(object)
    progress_text = Signal(str)

class ScrapeWorker(QRunnable):
    def __init__(self, db_path, scraper, url, mode):
        super().__init__()
        self.db_path, self.scraper, self.url, self.mode = db_path, scraper, url, mode
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            if self.mode == 'preview':
                results = self.scraper.preview_thread(self.url)
                self.signals.preview_done.emit(results)
                return
            db = Database(self.db_path)  # separate DB connection in worker thread
            if self.mode == 'quick':
                result = self.scraper.scan_profile(self.url)
                identity = db.save_profile(result, self.scraper.source_name)
            else:
                result = self.scraper.scan_details(self.url)
                identity = db.save_details(self.url, result)
            self.signals.done.emit(identity, self.mode)
        except Exception as exc:
            self.signals.failed.emit(f'{type(exc).__name__}: {exc}')


class ImageDownloadWorker(QRunnable):
    def __init__(self, db_path, actress_id):
        super().__init__()
        self.db_path = db_path
        self.actress_id = actress_id
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = download_images(
                Database(self.db_path), self.actress_id,
                progress=self.signals.progress_text.emit
            )
            self.signals.download_done.emit(result)
        except Exception as exc:
            self.signals.failed.emit(f'{type(exc).__name__}: {exc}')


class ImageViewer(QWidget):
    """JAV-style actress gallery: large image with previous/next below it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.urls = []
        self.index = 0
        self.on_delete = None
        self.on_download = None
        self.original = QPixmap()
        self.gif_movie = None
        self.gif_buffer = None
        self.request_reply = None
        self.network = QNetworkAccessManager(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = QLabel('Select an actress to view images')
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(260, 270)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setStyleSheet(
            'background:#111822; border:1px solid #354357; border-radius:6px; color:#a4b5c9;'
        )
        layout.addWidget(self.image_label, 1)

        nav = QHBoxLayout()
        self.previous = QPushButton('◀  Previous')
        self.next = QPushButton('Next  ▶')
        self.counter = QLabel('0 / 0')
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.open_btn = QPushButton('Open Original')
        self.previous.clicked.connect(lambda: self.move(-1))
        self.next.clicked.connect(lambda: self.move(1))
        self.open_btn.clicked.connect(self.open_original)
        nav.addWidget(self.previous)
        nav.addWidget(self.counter, 1)
        nav.addWidget(self.next)
        nav.addWidget(self.open_btn)
        layout.addLayout(nav)
        actions = QHBoxLayout()
        self.download_btn = QPushButton('Download All Images')
        self.delete_btn = QPushButton('Delete Current Image')
        self.download_btn.clicked.connect(lambda: self.on_download() if self.on_download else None)
        self.delete_btn.clicked.connect(lambda: self.on_delete() if self.on_delete else None)
        actions.addWidget(self.download_btn)
        actions.addWidget(self.delete_btn)
        layout.addLayout(actions)
        self.current_url = QLabel()
        self.current_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.current_url.setWordWrap(True)
        self.current_url.setStyleSheet('color:#9eb0c5; font-size:11px;')
        layout.addWidget(self.current_url)
        self._update_buttons()

    def _update_buttons(self):
        enabled = len(self.urls) > 0
        self.previous.setEnabled(len(self.urls) > 1)
        self.next.setEnabled(len(self.urls) > 1)
        self.open_btn.setEnabled(enabled)
        self.delete_btn.setEnabled(enabled)
        self.download_btn.setEnabled(enabled)
        self.counter.setText(f'{self.index + 1} / {len(self.urls)}' if enabled else '0 / 0')

    def set_images(self, items):
        # SQLite rows give us a stable image ID and optional local file path.
        self.items = [dict(item) for item in items]
        self.urls = [item['image_url'] for item in self.items]
        self.index = 0
        self._load_current()

    def move(self, direction):
        if not self.urls:
            return
        self.index = (self.index + direction) % len(self.urls)
        self._load_current()

    def open_original(self):
        if self.urls:
            QDesktopServices.openUrl(QUrl(self.urls[self.index]))

    def _load_current(self):
        # Clear the reference before abort(): abort can synchronously trigger
        # finished, which otherwise clears self.request_reply in the callback.
        pending = self.request_reply
        self.request_reply = None
        if pending is not None:
            pending.abort()
            pending.deleteLater()
        self._stop_animation()
        self.original = QPixmap()
        self.image_label.clear()
        self._update_buttons()
        if not self.urls:
            self.current_url.clear()
            self.image_label.setText('No images stored for this actress')
            return

        item = self.items[self.index]
        url = item['image_url']
        self.current_url.setText(url)
        local = item.get('local_path', '')
        if local and Path(local).is_file():
            if Path(local).suffix.lower() == '.gif':
                if self._play_gif(path=local):
                    return
            pixmap = QPixmap(local)
            if not pixmap.isNull():
                self.original = pixmap
                self._rescale()
                return
        self.image_label.setText('Loading image...')
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b'User-Agent', b'Mozilla/5.0 ImageScraper/0.2')
        reply = self.network.get(request)
        self.request_reply = reply
        reply.finished.connect(lambda reply=reply: self._image_finished(reply))

    def _stop_animation(self):
        movie = self.gif_movie
        self.gif_movie = None
        if movie is not None:
            movie.stop()
            movie.deleteLater()
        buffer = self.gif_buffer
        self.gif_buffer = None
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()

    def _play_gif(self, path=None, data=None):
        """Play an animated GIF from disk or a downloaded response buffer."""
        if path is not None:
            movie = QMovie(str(path), b'gif', self)
        else:
            self.gif_buffer = QBuffer(self)
            self.gif_buffer.setData(QByteArray(data))
            if not self.gif_buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                self.gif_buffer.deleteLater()
                self.gif_buffer = None
                return False
            movie = QMovie(self.gif_buffer, b'gif', self)

        if not movie.isValid():
            movie.deleteLater()
            if self.gif_buffer is not None:
                self.gif_buffer.close()
                self.gif_buffer.deleteLater()
                self.gif_buffer = None
            return False

        self.gif_movie = movie
        movie.frameChanged.connect(self._rescale)
        movie.start()
        self._rescale()
        return True

    def _image_finished(self, reply):
        if reply is not self.request_reply:
            return
        self.request_reply = None
        if reply.error():
            self.image_label.setText('Image could not be loaded. Try Open Original.')
        else:
            # Detect the actual GIF signature, not only the filename extension.
            # Image hosts may serve GIFs through extensionless URLs.
            data = bytes(reply.readAll())
            if data.startswith((b'GIF87a', b'GIF89a')):
                if not self._play_gif(data=data):
                    self.image_label.setText('GIF could not be played. Try Open Original.')
            else:
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    self.original = pixmap
                    self._rescale()
                else:
                    self.image_label.setText('Invalid image response. Try Open Original.')
        reply.deleteLater()

    def _rescale(self, *_):
        size = self.image_label.size() - QSize(12, 12)
        if size.width() <= 0 or size.height() <= 0:
            return
        if self.gif_movie is not None:
            frame = self.gif_movie.currentPixmap()
            if not frame.isNull():
                self.image_label.setPixmap(
                    frame.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                )
        elif not self.original.isNull():
            self.image_label.setPixmap(
                self.original.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ImageScraper — Profile & Image Library')
        self.resize(1390, 850)
        self.setMinimumSize(1050, 650)
        self.setStyleSheet(STYLE)
        self.db = Database()
        self.scrapers = [FamousBoardScraper(), ExampleScraper()]
        self.pool = QThreadPool.globalInstance()
        self.selected_id = None
        self.busy = False
        self._workers = []
        self._build()
        self.refresh()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        sidebar = QFrame(objectName='sidebar')
        sidebar.setFixedWidth(215)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(12,22,12,12)
        brand = QLabel('◈  ImageScraper')
        brand.setStyleSheet('font-size:19px;font-weight:700;color:#73bcff;padding:9px;')
        sl.addWidget(brand)
        sl.addWidget(QLabel('PROFILE DATABASE  •  v0.2.0'))
        sl.addSpacing(19)
        self.stack = QStackedWidget()
        self.nav = []
        for index, (label, builder) in enumerate([
            ('Dashboard', self._dashboard), ('Actress Library', self._library),
            ('Web Scraper', self._scraper), ('Image Manager', self._images),
            ('Settings', self._settings),
        ]):
            b = QPushButton(label)
            b.setObjectName('nav')
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False, n=index: self.navigate(n))
            sl.addWidget(b)
            self.nav.append(b)
            self.stack.addWidget(builder())
        sl.addStretch()
        sl.addWidget(QLabel('Local-first • SQLite'))
        outer.addWidget(sidebar)
        outer.addWidget(self.stack,1)
        self.navigate(0)
        self.statusBar().showMessage(f'Ready  •  {self.db.path}')

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for n, b in enumerate(self.nav):
            b.setChecked(n == index)
        if index in (0,1,3):
            self.refresh()

    @staticmethod
    def _page(title, subtitle):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(25,23,25,20)
        layout.setSpacing(15)
        heading = QLabel(title)
        heading.setStyleSheet('font-size:25px;font-weight:700;')
        layout.addWidget(heading)
        label = QLabel(subtitle)
        label.setStyleSheet('color:#9eb0c5;')
        layout.addWidget(label)
        return w,layout

    def _dashboard(self):
        w,l = self._page('Dashboard','Overview of locally indexed profiles and image records.')
        stats = QHBoxLayout()
        self.stat_labels = {}
        for name in ('Actresses','Source Profiles','Images','Links'):
            panel = QGroupBox(name)
            pl = QVBoxLayout(panel)
            value = QLabel('0')
            value.setStyleSheet('font-size:32px;font-weight:700;color:#73bcff;')
            pl.addWidget(value)
            stats.addWidget(panel)
            self.stat_labels[name] = value
        l.addLayout(stats)
        tips = QGroupBox('Getting started')
        tl = QVBoxLayout(tips)
        tl.addWidget(QLabel('1. Open Web Scraper and enter a profile URL.'))
        tl.addWidget(QLabel('2. Quick Scan stores the profile; Deep Scan follows for gallery images and links.'))
        tl.addWidget(QLabel('3. Add site-specific parsing in scrapers/example.py (currently a placeholder).'))
        tl.addWidget(QLabel('4. Use Actress Library to browse records shared by the SQLite database.'))
        l.addWidget(tips)
        go = QPushButton('Open Web Scraper')
        go.setObjectName('primary')
        go.clicked.connect(lambda: self.navigate(2))
        l.addWidget(go)
        l.addStretch()
        return w

    def _library(self):
        w,l = self._page('Actress Library','Find profiles and view their linked sources, aliases, images and URLs.')
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search actress name or alias...')
        self.search.textChanged.connect(self.refresh)
        btn = QPushButton('Refresh')
        btn.clicked.connect(self.refresh)
        toolbar.addWidget(self.search,1)
        toolbar.addWidget(btn)
        l.addLayout(toolbar)
        split = QSplitter()
        self.table = QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['ID','Name','Sources','Images'])
        self.table.setColumnHidden(0,True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_selected)
        split.addWidget(self.table)
        detail = QWidget()
        dl = QVBoxLayout(detail)
        self.heading = QLabel('Select an actress')
        self.heading.setStyleSheet('font-size:20px;font-weight:600;')
        dl.addWidget(self.heading)
        tabs = QTabWidget()
        self.profile_list = QListWidget()
        self.alias_list = QListWidget()
        self.image_viewer = ImageViewer()
        self.image_viewer.on_delete = self.delete_current_image
        self.image_viewer.on_download = self.download_selected_images
        self.link_list = QListWidget()
        for lst in (self.profile_list,self.link_list):
            lst.itemDoubleClicked.connect(self.open_item_url)
        tabs.addTab(self.profile_list,'Sources')
        tabs.addTab(self.alias_list,'Aliases')
        tabs.addTab(self.image_viewer,'Images')
        tabs.addTab(self.link_list,'Links')
        dl.addWidget(tabs,1)
        self.description = QPlainTextEdit()
        self.description.setReadOnly(True)
        self.description.setPlaceholderText('Description')
        self.description.setMaximumHeight(120)
        dl.addWidget(self.description)
        split.addWidget(detail)
        split.setSizes([450,730])
        l.addWidget(split,1)
        return w

    def _scraper(self):
        w,l = self._page('Web Scraper','Two-stage workflow: first extract profile metadata, then gallery images and links.')
        box = QGroupBox('Profile URL')
        form = QVBoxLayout(box)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('https://example.com/actress/profile')
        form.addWidget(self.url_input)
        actions = QHBoxLayout()
        self.profile_btn = QPushButton('1  Quick Scan — Profile')
        self.profile_btn.setObjectName('primary')
        self.profile_btn.clicked.connect(lambda: self.run_scan('quick'))
        self.detail_btn = QPushButton('2  Deep Scan — Images & Links')
        self.detail_btn.clicked.connect(lambda: self.run_scan('deep'))
        actions.addWidget(self.profile_btn)
        actions.addWidget(self.detail_btn)
        form.addLayout(actions)
        self.preview_btn = QPushButton('Test Single Thread — Preview Only')
        self.preview_btn.clicked.connect(lambda: self.run_scan('preview'))
        form.addWidget(self.preview_btn)
        self.url_input.setText('https://www.famousboard.com/threads/118087-Curvyllama')
        l.addWidget(box)
        self.progress = QProgressBar()
        self.progress.setRange(0,1)
        self.progress.setValue(0)
        l.addWidget(self.progress)
        loggroup = QGroupBox('Scan activity')
        logl = QVBoxLayout(loggroup)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText('Start a scan to see status messages...')
        logl.addWidget(self.log)
        l.addWidget(loggroup,1)
        preview_box = QGroupBox('Single-thread results (not saved to database)')
        preview_layout = QVBoxLayout(preview_box)
        self.preview_summary = QLabel('Run Test Single Thread to inspect posts and image URLs.')
        preview_layout.addWidget(self.preview_summary)
        self.preview_table = QTableWidget(0, 4)
        self.preview_table.setHorizontalHeaderLabels(['Post ID', 'Title', 'Preferred image URL', 'URL fingerprint'])
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.preview_table.cellDoubleClicked.connect(self.open_preview_row)
        preview_layout.addWidget(self.preview_table)
        l.addWidget(preview_box, 2)
        note = QLabel('One preferred URL per image. SHA-256 shown is a URL fingerprint, not a downloaded file checksum. Preview does not save.')
        note.setStyleSheet('color:#a4b5c9;')
        l.addWidget(note)
        return w

    def _images(self):
        w,l = self._page('Image Manager','Image records collected by scrapers, including local downloaded paths.')
        self.image_summary = QLabel('No image records yet')
        l.addWidget(self.image_summary)
        self.all_images = QTableWidget(0,3)
        self.all_images.setHorizontalHeaderLabels(['Actress','Image URL','Local path'])
        self.all_images.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.all_images.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.all_images.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.all_images.cellDoubleClicked.connect(self.open_image_row)
        l.addWidget(self.all_images,1)
        return w

    def _settings(self):
        w,l = self._page('Settings','Application paths and scraper configuration.')
        group = QGroupBox('Storage')
        form = QFormLayout(group)
        self.db_label = QLineEdit(str(self.db.path))
        self.db_label.setReadOnly(True)
        form.addRow('SQLite database:',self.db_label)
        images = Path(__file__).resolve().parents[1] / 'data' / 'Image'
        self.image_path = QLineEdit(str(images))
        self.image_path.setReadOnly(True)
        form.addRow('Downloaded image directory:',self.image_path)
        l.addWidget(group)
        info = QGroupBox('Integration')
        il = QVBoxLayout(info)
        il.addWidget(QLabel('Other Python applications can read this database using app.db.Database.'))
        il.addWidget(QLabel('Keep SQLite and downloaded files out of Git; back them up separately.'))
        il.addWidget(QLabel('Source-specific scraping settings will be added as website adapters are implemented.'))
        l.addWidget(info)
        l.addStretch()
        return w

    def refresh(self, *_):
        if not hasattr(self,'table'):
            return
        rows = self.db.all_actresses(self.search.text())
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        target_row = -1
        for row, rec in enumerate(rows):
            for col, v in enumerate((rec['id'],rec['display_name'],rec['source_count'],rec['image_count'])):
                self.table.setItem(row,col,QTableWidgetItem(str(v)))
            if rec['id'] == self.selected_id:
                target_row = row
        self.table.blockSignals(False)
        if target_row >= 0:
            self.table.selectRow(target_row)
            self.show_selected()
        else:
            self.table.clearSelection()
            self.selected_id = None
            self.image_viewer.set_images([])
        with self.db.connect() as conn:
            for name, table in (('Actresses','actresses'),('Source Profiles','profiles'),('Images','images'),('Links','links')):
                self.stat_labels[name].setText(str(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]))
            image_rows = conn.execute('''SELECT a.display_name, i.image_url, i.local_path
                FROM images i JOIN actresses a ON a.id=i.actress_id ORDER BY i.id DESC''').fetchall()
        self.image_summary.setText(f'{len(image_rows)} stored image URLs  •  double-click to open')
        self.all_images.setRowCount(len(image_rows))
        for row, rec in enumerate(image_rows):
            for col, val in enumerate(rec):
                self.all_images.setItem(row,col,QTableWidgetItem(val or ''))

    def show_selected(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        id_item = self.table.item(row,0)
        if not id_item:
            return
        self.selected_id = int(id_item.text())
        actress, profiles, aliases, links, images = self.db.details(self.selected_id)
        if not actress:
            return
        self.heading.setText(actress['display_name'])
        self.description.setPlainText(actress['description'])
        for lst in (self.profile_list,self.alias_list,self.link_list):
            lst.clear()
        for p in profiles:
            self._add_url(self.profile_list, f"{p['source_name']}  •  {p['status']}  •  {p['source_url']}",p['source_url'])
        for a in aliases:
            self.alias_list.addItem(a['alias'])
        self.image_viewer.set_images(images)
        for link in links:
            self._add_url(self.link_list,f"{link['label']}  •  {link['url']}",link['url'])

    def download_selected_images(self):
        if self.busy or self.selected_id is None:
            return
        self.busy = True
        self.image_viewer.download_btn.setEnabled(False)
        worker = ImageDownloadWorker(self.db.path, self.selected_id)
        worker.signals.download_done.connect(self.download_finished)
        worker.signals.progress_text.connect(self.statusBar().showMessage)
        worker.signals.failed.connect(self.download_failed)
        self._workers.append(worker)
        self.statusBar().showMessage('Downloading images...')
        self.pool.start(worker)

    def download_finished(self, result):
        saved, skipped, failed, errors = result
        self.busy = False
        self._workers.clear()
        self.refresh()
        self.statusBar().showMessage(
            f'Downloads complete: {saved} saved, {skipped} skipped, {failed} failed'
        )
        if errors:
            QMessageBox.warning(self, 'Image download results',
                f'{saved} saved, {skipped} skipped, {failed} failed.\n\n'
                + '\n'.join(errors[:12]))
        else:
            QMessageBox.information(self, 'Image downloads',
                f'{saved} downloaded, {skipped} already present.')

    def download_failed(self, reason):
        self.busy = False
        self._workers.clear()
        self.refresh()
        QMessageBox.warning(self, 'Download failed', reason)

    def delete_current_image(self):
        if self.busy or self.selected_id is None or not self.image_viewer.items:
            return
        item = self.image_viewer.items[self.image_viewer.index]
        local = item.get('local_path', '')
        message = 'Remove this image record from the database?'
        if local:
            message += '\nIts downloaded file will also be permanently deleted.'
        if QMessageBox.question(
            self, 'Delete image', message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.db.remove_image(self.selected_id, item['id']):
                self.refresh()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Delete failed', str(exc))

    @staticmethod
    def _add_url(list_widget, label, url):
        list_widget.addItem(label)
        list_widget.item(list_widget.count()-1).setData(Qt.ItemDataRole.UserRole,url)

    def open_item_url(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def open_image_row(self, row, col):
        item = self.all_images.item(row,1)
        if item:
            QDesktopServices.openUrl(QUrl(item.text()))

    def run_scan(self, mode):
        if self.busy:
            return
        url = self.url_input.text().strip()
        if not url.startswith(('https://','http://')):
            QMessageBox.warning(self,'Invalid URL','Enter a complete http:// or https:// profile URL.')
            return
        scraper = next((s for s in self.scrapers if s.supports(url)),None)
        if scraper is None:
            QMessageBox.warning(self,'Unsupported URL','No scraper adapter supports this URL.')
            return
        if mode == 'deep':
            with self.db.connect() as conn:
                if not conn.execute('SELECT id FROM profiles WHERE source_url=?',(url,)).fetchone():
                    QMessageBox.information(self,'Quick Scan required','Run the Quick Scan first for this exact profile URL.')
                    return
        worker = ScrapeWorker(self.db.path,scraper,url,mode)
        worker.signals.done.connect(self.scan_done)
        worker.signals.preview_done.connect(self.scan_preview_done)
        worker.signals.failed.connect(self.scan_failed)
        self._workers.append(worker)
        self.busy = True
        self.profile_btn.setEnabled(False)
        self.detail_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.progress.setRange(0,0)
        self.log.appendPlainText(f'[{mode.upper()}] {url}')
        self.statusBar().showMessage(f'Running {mode} scan')
        self.pool.start(worker)

    def _reset_scan(self):
        self.busy = False
        self._workers.clear()
        self.profile_btn.setEnabled(True)
        self.detail_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)
        self.progress.setRange(0,1)
        self.progress.setValue(1)

    def open_preview_row(self, row, col):
        # Prefer the candidate image URL; double-clicking opens in a browser.
        item = self.preview_table.item(row, 2)
        if item and item.text().startswith(('http://', 'https://')):
            QDesktopServices.openUrl(QUrl(item.text()))

    def scan_preview_done(self, records):
        self._reset_scan()
        image_count = sum(len(p['images']) for p in records)
        scanned = sum(p['image_tags'] for p in records)
        duplicates = sum(p['duplicates_skipped'] for p in records)
        self.preview_summary.setText(f'{len(records)} posts • {scanned} image tags • {image_count} unique images • {duplicates} duplicates removed • preview only')
        self.preview_table.setRowCount(image_count)
        row = 0
        for post in records:
            for img in post['images']:
                values = (post['post_id'], post['title'], img['image_url'], img['fingerprint'])
                for col, value in enumerate(values):
                    self.preview_table.setItem(row, col, QTableWidgetItem(str(value or '')))
                row += 1
        self.log.appendPlainText(f'Preview complete: {len(records)} posts; {scanned} image tags, {image_count} unique images, {duplicates} duplicates skipped (not saved)')
        self.statusBar().showMessage('Single-thread test completed')

    def scan_done(self, identity, mode):
        self._reset_scan()
        self.selected_id = identity
        self.log.appendPlainText(f'✔ {mode.title()} scan complete — actress ID {identity}')
        self.refresh()
        self.statusBar().showMessage(f'Scan complete • ID {identity}')

    def scan_failed(self, reason):
        self._reset_scan()
        self.log.appendPlainText(f'✖ {reason}')
        self.statusBar().showMessage('Scan failed')
        QMessageBox.warning(self,'Scan failed',reason)
