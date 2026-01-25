# Pdf2Markdown - API Reference

## Command-Line Interface

### Synopsis

```bash
uv run main.py <input_file> [output_file] [--extract-images]
```

### Arguments

#### Positional Arguments

**`input_file`** (required)
- Type: File path (string)
- Description: Path to the source file to convert
- Supported formats: PDF, DOCX, XLSX, PPTX, HTML, images, and more
- Must exist and be readable

**`output_file`** (optional)
- Type: File path (string)
- Description: Path to the destination Markdown file
- Default: If omitted, output is sent to stdout
- Parent directory must exist or be creatable

#### Optional Arguments

**`--extract-images`**
- Type: Flag (boolean)
- Description: Extract images from PDF files
- Default: False (disabled)
- Requirements:
  - Only works with PDF input files
  - Requires `output_file` to be specified
  - PyMuPDF must be installed

**`--help`**, **`-h`**
- Type: Flag
- Description: Show help message and exit

### Exit Codes

- `0` - Success
- `1` - Error (file not found, conversion failed, etc.)

## Supported File Formats

### Input Formats

| Format | Extensions | Image Extraction | Notes |
|--------|-----------|------------------|-------|
| PDF | `.pdf` | Yes (optional) | Uses pdfminer for text, PyMuPDF for images |
| Word | `.docx` | No | Preserves headings, tables, styles |
| Excel | `.xlsx`, `.xls` | No | Converts tables to markdown |
| PowerPoint | `.pptx` | No | Extracts slide content |
| HTML | `.html`, `.htm` | No | Converts to markdown syntax |
| Images | `.jpg`, `.png`, `.gif`, etc. | N/A | Can use LLM for captions (if configured) |

### Output Format

- Always Markdown (`.md`)
- UTF-8 encoding
- GitHub-flavoured Markdown syntax

## Image Extraction Details

### Process

When `--extract-images` is enabled for PDF files:

1. **Folder creation**: Creates `{output_filename}_images/` directory
2. **Image extraction**: Iterates through PDF pages and extracts images
3. **Size filtering**: Filters out images smaller than 100×100 pixels
4. **Format preservation**: Saves images in their original format
5. **Reference insertion**: Appends image references to markdown

### Image Naming Convention

```
image_{page:03d}_{index:03d}.{ext}
```

Examples:
- `image_001_001.png` - First image from page 1
- `image_005_002.jpg` - Second image from page 5
- `image_042_001.png` - First image from page 42

### Image Reference Format

Images are referenced in the markdown using relative paths:

```markdown
![Image {page}-{index}]({folder_name}/image_{page:03d}_{index:03d}.{ext})
```

Example output in markdown:
```markdown
![Image 1-1](output_images/image_001_001.png)
```

### Size Filtering

**Minimum dimensions**: 100×100 pixels (width and height)

**Rationale**: Filters out:
- Small logos
- Icons
- Decorative elements
- Watermarks

**Override**: Currently not configurable (hardcoded in `pdf_image_extractor.py:54`)

### Supported Image Formats

PyMuPDF extracts images in their native format:
- JPEG (`.jpg`, `.jpeg`)
- PNG (`.png`)
- GIF (`.gif`)
- BMP (`.bmp`)
- TIFF (`.tiff`)
- And others supported by PyMuPDF

## Python API

### Module: `pdf_image_extractor`

#### `create_image_folder(output_md_path: str) -> str`

Create images folder based on output markdown filename.

**Parameters:**
- `output_md_path` (str): Path to the output markdown file

**Returns:**
- str: Path to the created images folder

**Behaviour:**
- Generates folder name: `{basename}_images/`
- Clears folder if it already exists
- Creates folder with parents if needed

**Example:**
```python
from pdf_image_extractor import create_image_folder

folder = create_image_folder("/path/to/output.md")
# Returns: "/path/to/output_images"
```

#### `extract_images_from_pdf(pdf_path: str, output_dir: str, min_size: tuple = (100, 100)) -> List[Dict]`

Extract images from PDF and save to output directory.

**Parameters:**
- `pdf_path` (str): Path to input PDF file
- `output_dir` (str): Directory to save extracted images
- `min_size` (tuple): Minimum image dimensions (width, height), default (100, 100)

**Returns:**
- List[Dict]: List of image metadata dictionaries

**Metadata structure:**
```python
{
    "page": int,          # Page number (1-indexed)
    "index": int,         # Image index on page (1-indexed)
    "path": str,          # Full path to saved image
    "filename": str,      # Image filename
    "width": int,         # Image width in pixels
    "height": int,        # Image height in pixels
    "format": str         # Image format (PNG, JPEG, etc.)
}
```

**Exceptions:**
- `ImportError`: PyMuPDF not installed
- `Exception`: PDF processing failed

**Example:**
```python
from pdf_image_extractor import extract_images_from_pdf

images = extract_images_from_pdf(
    "document.pdf",
    "output_images",
    min_size=(150, 150)
)

for img in images:
    print(f"Page {img['page']}: {img['filename']} ({img['width']}×{img['height']})")
```

#### `insert_image_references(markdown_text: str, images: List[Dict], folder_name: str) -> str`

Insert image references into markdown text.

**Parameters:**
- `markdown_text` (str): Original markdown text
- `images` (List[Dict]): List of image metadata dicts
- `folder_name` (str): Name of images folder (for relative paths)

**Returns:**
- str: Markdown text with image references appended

**Behaviour:**
- Appends "## Extracted Images" section to the end
- Creates markdown image references for each image
- Uses relative paths to images folder

**Example:**
```python
from pdf_image_extractor import insert_image_references

markdown = "# Document Title\n\nSome text..."
images = [{"page": 1, "index": 1, "filename": "image_001_001.png"}]

result = insert_image_references(markdown, images, "output_images")
# Appends:
# ## Extracted Images
#
# ![Image 1-1](output_images/image_001_001.png)
```

## Dependencies

### Required

- **Python**: 3.13+
- **uv**: Package manager
- **markitdown**: 0.1.4+ (with `[all]` extras)

### Optional

- **PyMuPDF** (fitz): 1.26.7+ (required for `--extract-images`)
- **Pillow**: Bundled with markitdown (used for image size checking)

### Installation

```bash
# Basic installation
cd /home/pi/WebApps/Pdf2Markdown
uv sync

# With image extraction support (already included)
uv add pymupdf
```

## Configuration Files

### `pyproject.toml`

Project metadata and dependencies:

```toml
[project]
name = "pdf2markdown"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "markitdown[all]>=0.1.4",
    "pymupdf==1.26.7",
]
```

### `.gitignore`

Excludes generated files:

```
*_images/      # Generated image folders
backups/       # Backup files
__pycache__/   # Python cache
.venv/         # Virtual environment
```

## Examples

### Example 1: Simple PDF to Markdown

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py ~/Documents/report.pdf ~/Documents/report.md
```

**Output:**
```
Successfully converted '/home/pi/Documents/report.pdf' to '/home/pi/Documents/report.md'
```

### Example 2: PDF with Image Extraction

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py ~/Documents/manual.pdf ~/Documents/manual.md --extract-images
```

**Output:**
```
Extracted 12 image(s) to '/home/pi/Documents/manual_images'
Successfully converted '/home/pi/Documents/manual.pdf' to '/home/pi/Documents/manual.md'
```

### Example 3: Stdout Mode

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py document.pdf > output.md
```

### Example 4: Batch Processing

```bash
cd /home/pi/WebApps/Pdf2Markdown

# Convert all PDFs in a directory
for pdf in ~/Documents/*.pdf; do
  basename="${pdf%.pdf}"
  uv run main.py "$pdf" "${basename}.md" --extract-images
done
```

### Example 5: Error Handling

```bash
cd /home/pi/WebApps/Pdf2Markdown
uv run main.py nonexistent.pdf output.md
```

**Output:**
```
Error: File 'nonexistent.pdf' not found.
```

**Exit code:** 1

## Limitations

1. **Image placement**: Images are appended at the end, not placed inline
2. **PDF only**: Image extraction only works with PDF files
3. **Size threshold**: Cannot configure minimum image size (hardcoded at 100×100px)
4. **Stdout limitation**: Image extraction requires output file path
5. **Text-only conversion**: PDFs are converted to plain text (minimal formatting)
6. **Page boundaries**: Text extraction doesn't preserve page breaks

## Future Enhancements

Potential improvements for future versions:

- Configurable minimum image size
- Inline image placement using heuristics
- Page boundary preservation
- Enhanced formatting for PDF tables
- Support for image extraction from PPTX files
- Batch processing built-in command
- Progress bars for large files

## Version History

- **v0.1.0** (2025-12-20): Initial release with PDF image extraction support
