"""Non-executing visual approximation for the ImageScraper Actress Library.

Only Qt widgets created here run; imported Python code is never imported/executed.
This first preview explicitly supports the ImageScraper fixture layout. It is not
a general-purpose arbitrary-source renderer.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSplitter, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QPlainTextEdit, QGroupBox, QSizePolicy
)

PREVIEW_STYLESHEET = """
QWidget { background: #151b24; color: #e7ecf4; font-size: 13px; }
QFrame#previewSidebar { background: #10151d; border-right: 1px solid #313b4b; }
QLineEdit, QPlainTextEdit, QTableWidget {
 background: #111822; border: 1px solid #354357; border-radius: 5px;
 padding: 7px; color: #e7ecf4;
}
QPushButton { background: #2b3a4c; border: 1px solid #41546b;
 border-radius: 6px; padding: 7px 10px; }
QPushButton#selectedNav { background: #24394f; border-left: 3px solid #58aaff; }
QHeaderView::section { background: #253144; color: #dbe6f6;
 border: none; padding: 8px; }
QTabWidget::pane { border: 1px solid #354357; }
QTabBar::tab { background: #1d2633; padding: 8px 12px; }
QTabBar::tab:selected { background: #304761; }
"""

class ImageScraperLibraryPreview(QWidget):
    """Safe replica of the layout structure, with a live QSplitter drag handle."""

    splitterChanged = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("imageScraperPreview")
        self.setStyleSheet(PREVIEW_STYLESHEET)
        self.setMinimumSize(880, 560)
        self._initializing = True
        horizontal = QHBoxLayout(self)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("previewSidebar")
        sidebar.setFixedWidth(185)
        nav = QVBoxLayout(sidebar)
        brand = QLabel("◈  ImageScraper")
        brand.setStyleSheet("color: #73bcff; font-size: 17px; font-weight: bold;")
        nav.addWidget(brand)
        nav.addWidget(QLabel("PROFILE DATABASE  •  v0.2.0"))
        nav.addSpacing(18)
        for name in ("Dashboard", "Actress Library", "Web Scraper", "Image Manager", "Settings"):
            button = QPushButton(name)
            if name == "Actress Library":
                button.setObjectName("selectedNav")
            button.setEnabled(False)
            nav.addWidget(button)
        nav.addStretch()
        nav.addWidget(QLabel("Preview only — no database"))
        horizontal.addWidget(sidebar)

        page = QWidget()
        content = QVBoxLayout(page)
        content.setContentsMargins(18, 16, 18, 14)
        title = QLabel("Actress Library")
        title.setStyleSheet("font-size: 23px; font-weight: bold;")
        content.addWidget(title)
        content.addWidget(QLabel("Find profiles and view their linked sources, aliases, images and URLs."))
        toolbar = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Search actress name or alias...")
        search.setReadOnly(True)
        toolbar.addWidget(search, 1)
        refresh = QPushButton("Refresh")
        refresh.setEnabled(False)
        toolbar.addWidget(refresh)
        content.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        table = QTableWidget(1, 3)
        table.setHorizontalHeaderLabels(["Name", "Sources", "Images"])
        table.setItem(0, 0, QTableWidgetItem("Example profile"))
        table.setItem(0, 1, QTableWidgetItem("1"))
        table.setItem(0, 2, QTableWidgetItem("30"))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setMinimumWidth(125)
        self.splitter.addWidget(table)

        detail = QWidget()
        detail.setMinimumWidth(270)
        right = QVBoxLayout(detail)
        heading = QLabel("Select an actress")
        heading.setStyleSheet("font-size: 18px; font-weight: bold;")
        right.addWidget(heading)
        tabs = QTabWidget()
        tabs.setMinimumHeight(260)
        for name in ("Sources", "Aliases", "Images", "Links"):
            pane = QWidget()
            if name == "Images":
                gallery = QVBoxLayout(pane)
                image = QLabel("Image viewer preview\n(no URLs or downloads are loaded)")
                image.setAlignment(Qt.AlignmentFlag.AlignCenter)
                image.setStyleSheet("background:#111822; border:1px solid #354357;")
                image.setMinimumHeight(180)
                image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                gallery.addWidget(image, 1)
                image_nav = QHBoxLayout()
                for label in ("◀ Previous", "0 / 0", "Next ▶", "Open Original"):
                    image_nav.addWidget(QPushButton(label))
                gallery.addLayout(image_nav)
                actions = QHBoxLayout()
                actions.addWidget(QPushButton("Download All Images"))
                actions.addWidget(QPushButton("Delete Current Image"))
                gallery.addLayout(actions)
            tabs.addTab(pane, name)
        tabs.setCurrentIndex(2)
        right.addWidget(tabs, 1)
        description = QPlainTextEdit()
        description.setReadOnly(True)
        description.setPlaceholderText("Description")
        description.setMaximumHeight(120)
        right.addWidget(description)
        self.splitter.addWidget(detail)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(9)
        self.splitter.setSizes([450, 730])
        self.splitter.splitterMoved.connect(self._splitter_moved)
        content.addWidget(self.splitter, 1)
        horizontal.addWidget(page, 1)
        self._initializing = False

    def set_split_sizes(self, sizes):
        """Load sizes from static source analysis without generating an edit."""
        if len(sizes) != 2:
            return
        self._initializing = True
        self.splitter.setSizes([max(1, int(v)) for v in sizes])
        self._initializing = False

    def current_split_sizes(self):
        return tuple(self.splitter.sizes()[:2])

    def _splitter_moved(self, _position, _index):
        if not self._initializing:
            left, right = self.current_split_sizes()
            self.splitterChanged.emit(left, right)
