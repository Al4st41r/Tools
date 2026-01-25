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