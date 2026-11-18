# PySide6 Director — MVP

A standalone PySide6 visual editor for **new, absolute-positioned UI designs**. This starter does not yet import arbitrary existing Python scripts, rewrite existing source files, or edit QVBoxLayout/QGridLayout layouts.

## Install in PyCharm (Windows)

1. Clone the repository and open it as a PyCharm project:
   ```powershell
   git clone https://github.com/RageVista/PySide6-Director.git
   cd PySide6-Director
   ```
2. Create a Python virtual environment with a compatible Python version.
3. In PyCharm's Terminal:
   ```powershell
   python -m pip install -r requirements.txt
   python main.py
   ```

## Use

- Click any widget in the left toolbox to add it to the 900×600 canvas.
- Drag the widget to reposition it; drag its bottom-right corner to resize.
- Select it to edit its text, object name, dimensions, or image path in the right panel.
- **Ctrl+S** saves an editable `.json` design file; **Ctrl+O** opens one.
- **F5** shows a runtime preview with interactive controls.
- **Ctrl+E** exports a standalone runnable `.py` file (e.g., `generated_ui.py`). Run it with `python generated_ui.py`.


## v0.2 — Inspect existing Python UIs (static, safe)

Choose **Import → Inspect existing Python UI...** or press **Ctrl+I** to open the new inspector. Open `tests/ImageScraper/gui.py` as the first test.

- Detects declared PySide6 widgets and layouts, grouped under their containing class/method.
- Select an item to inspect supported literal properties such as fixed width, height, margins, spacing, text, placeholders and splitter sizes.
- Edit one property and select **Apply property change (in memory)** to display a unified source diff.
- Choose **Save as copy...** to write a modified `.py` file. The original is protected. No target module is imported or executed.
- **Discard edits** resets the in-memory copy to the source loaded from disk.
- Run parser regression tests: `python -m unittest discover -s tests -p "test_*.py"`.

**Current limits:** This is a structural/code inspector, not a pixel-perfect rendered preview of imported scripts. Widget dragging in the original fixed-position canvas remains for *new* designs only. Existing QLayouts require rules-based restructuring rather than absolute positioning. This version intentionally makes no claims about safely round-tripping arbitrary Python or resolving source dependencies.

## v0.3 — ImageScraper visual preview and source editing

Use **Import → Inspect existing Python UI... (Ctrl+I)** and open `tests/ImageScraper/gui.py`.

The inspector now has **Visual Designer**, **Widget Tree**, and **Source Changes** tabs.

1. The **Visual Designer** renders a safe Qt approximation of the ImageScraper Actress Library page. The imported script is parsed statically, never imported or executed; no database, networking or scraping occurs.
2. **Drag the divider** between the actress table and the preview area. The displayed pane sizes update while dragging.
3. Select **Apply splitter sizes to source**. Director modifies only `MainWindow._library`'s two literal values in `split.setSizes([450,730])` and switches to **Source Changes** for a unified diff.
4. Select **Save as copy...** to export `gui_director_edit.py`. The original `gui.py` remains untouched. Alternatively choose **Discard edits** to reset.

**Scope:** This preview deliberately reconstructs one known test page, not arbitrary imported Python. The preview is visually approximate, using placeholder data and Qt native layout widgets. It does **not** yet support drag-to-move arbitrary imported widgets, live binding to application data, user stylesheets, or automatic source rewrites beyond supported literal edits. For other scripts, the Visual Designer tab is disabled unless the known splitter pattern is found.

Regression tests:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## Constraints and next engineering milestones

- **Fixed positioning only** in MVP; later support managed layouts with margins, spacing and stretch factors.
- Save **JSON** as the editable design source. Exported Python is **one-way** and should not be edited then round-tripped yet.
- Import and rewrite of existing `.py` requires a source parser, safe transformation engine, isolated runner, and code preservation strategy. Do not execute untrusted Python through the designer.
- Image paths may be absolute. Later project bundles should copy assets and use project-relative resource paths.
- Design canvas is fixed at 900×600, and property updates do not yet implement undo/redo, snap guides or collision detection.
- Generated widgets are named `self.widget_N` and preserve configured `objectName`; later export can generate meaningful Python field names.

## Project structure

```text
PySide6-Director/
  main.py
  python_importer.py
  visual_preview.py
  requirements.txt
  README.md
  .gitignore
  tests/
    test_python_importer.py
    ImageScraper/
      gui.py
      README.md
```
