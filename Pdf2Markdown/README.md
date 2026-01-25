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
- **--clean**: Post-process text to fix broken sentences and layout issues (Recommended)
- **--split-chapters**: Split output into separate files by chapter (H1 headers)

### Features

#### 1. Layout-Aware Text Extraction
The tool automatically detects multi-column layouts in PDFs and extracts text in the correct reading order (Left Column -> Right Column), preventing "interleaved" text issues common with basic extractors.

#### 2. Text Cleaning (`--clean`)
PDFs often contain hard line breaks within sentences. The `--clean` option:
- Merges broken lines into coherent paragraphs.
- Preserves headers and structural formatting.
- Removes excessive whitespace.
- Intelligently handles paragraph breaks.

#### 3. Image Extraction (`--extract-images`)
- Extracts images to a `{output_file}_images/` subfolder.
- Automatically inserts image references into the Markdown.
- Filters out small icons/logos (< 100×100px).
- Preserves original image formats.

## Examples

### Basic Conversion
```bash
# Convert PDF to file
uv run main.py document.pdf output.md
```

### Recommended Usage (Clean Text)
```bash
# Convert with text cleaning for better readability
uv run main.py document.pdf output.md --clean
```

### Full Extraction (Images + Text)
```bash
# Extract images and clean text
uv run main.py document.pdf output.md --extract-images --clean
```

### Split by Chapters
```bash
# Split large documents into separate markdown files per chapter
uv run main.py document.pdf output.md --split-chapters --clean
```

## Limitations
- Image extraction only works with PDF files
- Image extraction requires an output file path (not available when using stdout)
- Small images (< 100×100px) are automatically filtered out

## Maintenance
- **Dependencies:** Managed in `pyproject.toml`. Update with `uv add`
- **Entry Point:** `main.py`
- **Core Modules:**
    - `pdf_image_extractor.py`: Handles PDF parsing, layout sorting, and image extraction.
    - `text_processor.py`: Handles text post-processing and cleaning.