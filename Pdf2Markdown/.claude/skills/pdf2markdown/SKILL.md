---
name: pdf2markdown
description: Convert PDF files to Markdown format with optional image extraction. Use when you need to extract text from PDFs, convert PDFs to Markdown, or extract images from PDF documents.
---

# PDF to Markdown Converter

## Overview

This skill uses the Pdf2Markdown converter to transform PDF files into clean Markdown format. It supports:

- PDF to Markdown text conversion
- Optional image extraction from PDFs
- Automatic filtering of small images (< 100×100px)
- Preservation of original image formats
- Output to file or stdout

## Prerequisites

Before using this skill, ensure:
- Dependencies are installed: `cd /home/pi/WebApps/Pdf2Markdown && uv sync`
- Python 3.13 is required
- The input file exists and is readable
- You have write permissions for the output directory

## Quick Start

### Basic Conversion (text only)

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py input.pdf output.md
```

### Conversion with Image Extraction

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py input.pdf output.md --extract-images
```

### Output to Stdout

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py input.pdf
```

## Common Tasks

### Convert a single PDF to Markdown

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py document.pdf document.md
```

**Expected output:**
- `document.md` - Markdown file with extracted text

### Convert PDF with image extraction

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py report.pdf report.md --extract-images
```

**Expected output:**
- `report.md` - Markdown file with text and image references
- `report_images/` - Folder containing extracted images

### Batch convert multiple PDFs

```bash
cd /home/pi/WebApps/Pdf2Markdown
for pdf in *.pdf; do
  uv run main.py "$pdf" "${pdf%.pdf}.md" --extract-images
done
```

### Convert other file formats

The tool also supports DOCX, XLSX, PPTX, and HTML files:

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py presentation.pptx output.md
uv run main.py spreadsheet.xlsx output.md
```

## Output Structure

When using `--extract-images` with PDF files:

```
output.md                    # Markdown file with content
output_images/               # Image folder
├── image_001_001.png        # Images from page 1
├── image_002_001.jpg        # Images from page 2
└── image_002_002.png        # Second image from page 2
```

Image references are appended to the markdown:

```markdown
## Extracted Images

![Image 1-1](output_images/image_001_001.png)

![Image 2-1](output_images/image_002_001.jpg)
```

## Important Notes

- **Image extraction** only works with PDF files
- **Small images** (< 100×100 pixels) are automatically filtered out to avoid logos/icons
- **Original formats** are preserved (JPEG, PNG, etc.)
- **Stdout mode** does not support image extraction (requires output file path)
- **Existing image folders** will be cleared and recreated

## Troubleshooting

### Command not found

Ensure you're in the correct directory:
```bash
cd /home/pi/WebApps/Pdf2Markdown
```

### Dependencies missing

Install dependencies:
```bash
cd /home/pi/WebApps/Pdf2Markdown
uv sync
```

### Permission denied

Check file permissions:
```bash
ls -la input.pdf
chmod 644 input.pdf
```

### No images extracted

This is normal if:
- The PDF contains no images
- All images are smaller than 100×100 pixels
- Images are embedded in unsupported formats

### PyMuPDF not installed warning

Install PyMuPDF:
```bash
cd /home/pi/WebApps/Pdf2Markdown
uv add pymupdf
```

## Getting Help

View command-line help:
```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py --help
```

See [REFERENCE.md](REFERENCE.md) for detailed API documentation.
