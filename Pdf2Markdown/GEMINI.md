# Pdf2Markdown

## Overview
Pdf2Markdown is a utility to convert various file formats (PDF, DOCX, XLSX, PPTX, HTML, etc.) into Markdown. It utilises Microsoft's `markitdown` library and supports optional image extraction and layout-aware text processing for PDF files.

## Environment
- **Language:** Python 3.13+
- **Dependency Manager:** uv
- **Libraries:** markitdown, PyMuPDF (fitz), Pillow

## Installation
```bash
uv sync
```

## Usage
Run the converter using `uv`:

```bash
uv run main.py <input_file> [output_file] [--extract-images] [--clean] [--split-chapters]
```

### Arguments
- **input_file**: Path to the source file (required)
- **output_file**: Path to the destination Markdown file (optional). If omitted, outputs to stdout
- **--extract-images**: Extract images from PDF files (optional)
- **--clean**: Post-process text to fix broken sentences, merge paragraphs, and normalize whitespace (Recommended for PDFs)
- **--split-chapters**: Split output into separate files by chapter (based on H1 headers)

### Features

#### Layout-Aware Extraction
For PDF files, the tool automatically uses PyMuPDF with column detection to correctly extract text from multi-column layouts (e.g. academic papers, newsletters), preventing text interleaving.

#### Image Extraction
When the `--extract-images` flag is used with PDF files:
- Images are extracted and saved to a subfolder named `{output_file}_images/`
- Image references are automatically inserted
- Images smaller than 100×100 pixels are filtered out
- Requires an output file to be specified

#### Text Cleaning (--clean)
- Joins broken lines into coherent paragraphs
- Respects headers and layout structure
- Fixes extra whitespace issues common in PDF extraction

## Examples
```bash
# Basic conversion
uv run main.py document.pdf output.md

# Convert with text cleaning (Recommended)
uv run main.py document.pdf output.md --clean

# Extract images and clean text
uv run main.py document.pdf output.md --extract-images --clean
```

## Web Application
The project includes a web interface in `webapp/`.

- **Live URL:** https://architools.drawingtable.net/pdf2markdown/
- **Documentation:** `webapp/README-WEBAPP.md`
- **Stack:** Flask, Nginx, Systemd
- **Service:** `pdf2markdown`

## Maintenance
- **Dependencies:** Managed in `pyproject.toml`. Update with `uv add`
- **Entry Point:** `main.py`
- **Modules:**
    - `pdf_image_extractor.py`: PDF specific handling (images, layout sorting)
    - `text_processor.py`: Text cleaning logic

---

# Drawio2PPTX

## Overview
Drawio2PPTX is a utility to convert Draw.io (`.drawio`, `.xml`) diagrams into editable Microsoft PowerPoint (`.pptx`) presentations. It preserves text editability and uses native PowerPoint connectors for lines and arrows.

## Environment
- **Language:** Python 3.13+
- **Dependency Manager:** uv
- **Libraries:** python-pptx, defusedxml, lxml

## Usage (CLI)
```bash
uv run main.py <input_file> <output_file>
```

## Web Application
- **Live URL:** https://architools.drawingtable.net/drawio2pptx/
- **Location:** `~/WebApps/Tools/Drawio2PPTX/webapp/`
- **Service:** `drawio2pptx` (Port 5003)

## Features
- **Editable Shapes:** Maps Draw.io shapes to native MSO AutoShapes.
- **Dynamic Connectors:** Uses native PowerPoint connectors that remain attached to shapes.
- **Multi-page Support:** Each Draw.io page/tab is converted to a separate slide.
- **Advanced Routing:** 
    - **Alignment-Based:** Detects geometric overlap to force logical flowchart directions.
    - **Straight-Line Optimization:** Forces clean straight lines for perfectly aligned nodes.
    - **Hybrid Heuristic:** Uses closest-point logic for curved/straight lines and cardinal direction logic for orthogonal elbows.
- **Arrowhead Support:** Low-level XML injection enables support for Block, Classic, Diamond, and Oval arrowheads with correct sizing and hollow/filled states.
- **Rich Text Parsing:** Robust HTML parser for bold, italic, underline, font color, and font size within labels.
- **Absolute Positioning:** Correctly calculates coordinates for nested shapes and groups by traversing the hierarchy.