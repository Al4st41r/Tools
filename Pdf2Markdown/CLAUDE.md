# Pdf2Markdown - Claude Code Configuration

## Commands
- **Run Converter:** `uv run main.py {input_file} [output_file] [--extract-images]`
- **Install Dependencies:** `uv sync`
- **Add Dependency:** `uv add {package}`
- **Test Basic Conversion:** `uv run main.py test.pdf output.md`
- **Test with Image Extraction:** `uv run main.py test.pdf output.md --extract-images`
- **View Help:** `uv run main.py --help`

## Project Structure
- `main.py`: Entry point script with argparse CLI
- `pdf_image_extractor.py`: Image extraction module for PDFs
- `pyproject.toml`: Dependency definitions
- `uv.lock`: Locked dependencies
- `README.md`: Main documentation
- `GEMINI.md`: General documentation

## Features
- Convert multiple file formats to Markdown (PDF, DOCX, XLSX, PPTX, HTML, etc.)
- Optional image extraction from PDF files using PyMuPDF
- Automatic filtering of small images (< 100×100px)
- Image references inserted into markdown output
- Original image formats preserved

## Style & Conventions
- Uses `uv` for package management
- Python 3.13
- Follows PEP 8
