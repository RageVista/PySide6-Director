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
  requirements.txt
  README.md
  .gitignore
```
