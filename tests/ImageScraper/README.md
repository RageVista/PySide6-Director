# ImageScraper import test

This directory contains a **copy** of the user's ImageScraper `app/gui.py` as a real-world input fixture for developing PySide6 Director's future Python UI importer.

## What to test

- `MainWindow._build()`: sidebar, navigation buttons, `QStackedWidget` and page builders.
- `MainWindow._library()`: `QHBoxLayout` toolbar, `QSplitter`, `QTableWidget`, `QTabWidget`, and description pane.
- `ImageViewer.__init__()`: image label, navigation and action buttons, nested vertical/horizontal layouts.
- `STYLE`: embedded Qt stylesheet and object-name selectors.
- Nested layouts, stretch factors, fixed widths, margins, minimum/maximum sizes, signals and slots.

## Important

This is **not a runnable standalone application**: the source imports `app.db`, `app.image_downloads`, and `scrapers.*`, which are not included. The fixture should first be parsed **statically**, without importing or executing it, to avoid invoking database, network or scraping functionality.

The original ImageScraper project is not altered by these tests. Later, any changes proposed by Director should be presented as a diff and written only after creating backups.
