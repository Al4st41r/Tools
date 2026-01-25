"""PDF image extraction module for Pdf2Markdown."""

import os
import io
import shutil
from typing import List, Dict, Tuple
from pathlib import Path

try:
    import fitz  # PyMuPDF
    from PIL import Image
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


def sort_blocks(blocks: List[Tuple]) -> List[Tuple]:
    """
    Sort blocks attempting to respect multi-column layouts.
    Sorts header/footer regions by Y, and body region by X then Y (columns).
    """
    if not blocks:
        return []

    # Estimate page height from max y1
    page_height = max(b[3] for b in blocks)
    
    # Define Header/Footer thresholds (10% top/bottom)
    header_thresh = page_height * 0.1
    footer_thresh = page_height * 0.9
    
    headers = []
    footers = []
    body = []
    
    for b in blocks:
        y0 = b[1]
        # Check center of block for region assignment? 
        # Or just top edge. y0 is top edge.
        if y0 < header_thresh:
            headers.append(b)
        elif y0 > footer_thresh:
            footers.append(b)
        else:
            body.append(b)
            
    # Sort Headers/Footers: Top-down, Left-right
    headers.sort(key=lambda b: (b[1], b[0]))
    footers.sort(key=lambda b: (b[1], b[0]))
    
    # Sort Body: Left-right (Columnar), then Top-down
    # This assumes the body is composed of columns.
    body.sort(key=lambda b: (b[0], b[1]))
    
    return headers + body + footers


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text from PDF using PyMuPDF (fitz) with block sorting.
    This handles multi-column layouts better than basic linear extraction.
    """
    if not PYMUPDF_AVAILABLE:
        raise ImportError("PyMuPDF is required for text extraction. Install with: uv add pymupdf")

    try:
        doc = fitz.open(pdf_path)
        text_content = []
        
        for page in doc:
            # get_text("blocks") returns list of (x0, y0, x1, y1, "lines", block_no, block_type)
            blocks = page.get_text("blocks")
            
            # Filter for text blocks only (type 0)
            text_blocks = [b for b in blocks if b[6] == 0]
            
            # Sort blocks by layout (columns)
            sorted_blocks = sort_blocks(text_blocks)
            
            for block in sorted_blocks:
                # block[4] is the text content
                # Strip trailing whitespace and newlines from each block
                text_content.append(block[4].strip())
        
        doc.close()
        # Join with a single newline to provide a continuous line stream for processing
        return "\n".join(text_content)
        
    except Exception as e:
        raise Exception(f"Failed to extract text from PDF: {e}")


def create_image_folder(output_md_path: str) -> str:
    """
    Create images folder based on output markdown filename.

    Args:
        output_md_path: Path to the output markdown file

    Returns:
        Path to the created images folder
    """
    # Get base name without extension
    base_name = Path(output_md_path).stem
    parent_dir = Path(output_md_path).parent

    # Create folder name: {basename}_images
    folder_name = f"{base_name}_images"
    folder_path = parent_dir / folder_name

    # Clear folder if it exists
    if folder_path.exists():
        shutil.rmtree(folder_path)

    # Create fresh folder
    folder_path.mkdir(parents=True, exist_ok=True)

    return str(folder_path)


def get_pdf_page_count(pdf_path: str) -> int:
    """
    Get the total number of pages in a PDF file.

    Args:
        pdf_path: Path to input PDF file

    Returns:
        Number of pages in the PDF
    """
    if not PYMUPDF_AVAILABLE:
        raise ImportError("PyMuPDF is required. Install with: uv add pymupdf")

    try:
        pdf_document = fitz.open(pdf_path)
        page_count = len(pdf_document)
        pdf_document.close()
        return page_count
    except Exception as e:
        raise Exception(f"Failed to read PDF: {e}")


def extract_images_from_pdf(
    pdf_path: str,
    output_dir: str,
    min_size: Tuple[int, int] = (100, 100)
) -> List[Dict[str, any]]:
    """
    Extract images from PDF and save to output directory.

    Args:
        pdf_path: Path to input PDF file
        output_dir: Directory to save extracted images
        min_size: Minimum image dimensions (width, height) to keep

    Returns:
        List of dicts with keys: page, index, path, width, height
    """
    if not PYMUPDF_AVAILABLE:
        raise ImportError("PyMuPDF is required for image extraction. Install with: uv add pymupdf")

    extracted_images = []

    try:
        pdf_document = fitz.open(pdf_path)

        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            image_list = page.get_images(full=True)

            for img_index, img in enumerate(image_list):
                try:
                    xref = img[0]

                    # Use Pixmap to get image with better colour handling
                    pix = fitz.Pixmap(pdf_document, xref)

                    # Convert to RGB if needed
                    if pix.n < 4:  # RGB or Grayscale without alpha
                        if pix.colorspace and pix.colorspace.n != 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)

                    width = pix.width
                    height = pix.height

                    # Filter out small images
                    if width < min_size[0] or height < min_size[1]:
                        pix = None
                        continue

                    # Convert pixmap to PIL Image
                    if pix.n == 1:  # Grayscale
                        img_obj = Image.frombytes("L", [pix.width, pix.height], pix.samples)
                    elif pix.n == 3:  # RGB
                        img_obj = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    elif pix.n == 4:  # RGBA
                        img_obj = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
                    else:
                        pix = None
                        continue

                    pix = None  # Free memory

                    # Detect if image has predominantly dark/black background
                    # Sample corners and edges
                    corners = [
                        img_obj.getpixel((0, 0)),
                        img_obj.getpixel((width-1, 0)),
                        img_obj.getpixel((0, height-1)),
                        img_obj.getpixel((width-1, height-1))
                    ]

                    # Check if corners are predominantly dark (RGB values < 50)
                    dark_corners = 0
                    for pixel in corners:
                        if isinstance(pixel, tuple):
                            avg = sum(pixel[:3]) / 3 if len(pixel) >= 3 else pixel[0]
                        else:
                            avg = pixel
                        if avg < 50:
                            dark_corners += 1

                    # If most corners are dark, replace dark pixels with white
                    if dark_corners >= 3:
                        # Convert to RGBA for processing
                        if img_obj.mode != 'RGBA':
                            img_obj = img_obj.convert('RGBA')

                        # Replace dark pixels with white
                        pixels = img_obj.load()
                        for y in range(height):
                            for x in range(width):
                                r, g, b, a = pixels[x, y]
                                # If pixel is very dark (likely background)
                                if r < 50 and g < 50 and b < 50:
                                    pixels[x, y] = (255, 255, 255, a)

                        # Convert back to RGB
                        background = Image.new('RGB', img_obj.size, (255, 255, 255))
                        background.paste(img_obj, mask=img_obj.split()[3])
                        img_obj = background

                    image_ext = 'png'  # Always save as PNG for consistency

                    # Generate filename: image_{page:03d}_{index:03d}.{ext}
                    image_filename = f"image_{page_num + 1:03d}_{img_index + 1:03d}.{image_ext}"
                    image_path = os.path.join(output_dir, image_filename)

                    # Save image using Pillow to handle transparency properly
                    img_obj.save(image_path, quality=95)

                    # Store metadata
                    extracted_images.append({
                        "page": page_num + 1,
                        "index": img_index + 1,
                        "path": image_path,
                        "filename": image_filename,
                        "width": width,
                        "height": height,
                        "format": image_ext.upper()
                    })

                except Exception as e:
                    # Skip corrupted images
                    print(f"Warning: Failed to extract image {img_index + 1} from page {page_num + 1}: {e}")
                    continue

        pdf_document.close()

    except Exception as e:
        raise Exception(f"Failed to process PDF: {e}")

    return extracted_images


def detect_chapters(markdown_text: str) -> List[Dict[str, any]]:
    """
    Detect chapters in markdown text based on H1 headers (#).

    Args:
        markdown_text: Markdown content to analyze

    Returns:
        List of dicts with keys: title, start_line, end_line, content
    """
    lines = markdown_text.split('\n')
    chapters = []
    current_chapter = None

    for i, line in enumerate(lines):
        # Detect H1 headers (lines starting with single #)
        if line.strip().startswith('# ') and not line.strip().startswith('## '):
            # Save previous chapter if it exists
            if current_chapter is not None:
                current_chapter['end_line'] = i - 1
                current_chapter['content'] = '\n'.join(lines[current_chapter['start_line']:i])
                chapters.append(current_chapter)

            # Start new chapter
            current_chapter = {
                'title': line.strip()[2:].strip(),  # Remove '# ' prefix
                'start_line': i,
                'end_line': None,
                'content': None
            }

    # Save last chapter
    if current_chapter is not None:
        current_chapter['end_line'] = len(lines) - 1
        current_chapter['content'] = '\n'.join(lines[current_chapter['start_line']:])
        chapters.append(current_chapter)

    # If no chapters found, treat entire document as one chapter
    if not chapters:
        chapters.append({
            'title': 'Document',
            'start_line': 0,
            'end_line': len(lines) - 1,
            'content': markdown_text
        })

    return chapters


def get_page_range_for_chapter(chapter_index: int, total_chapters: int, total_pages: int) -> Tuple[int, int]:
    """
    Estimate page range for a chapter based on equal distribution.

    Args:
        chapter_index: Index of the chapter (0-based)
        total_chapters: Total number of chapters
        total_pages: Total number of pages in PDF

    Returns:
        Tuple of (start_page, end_page) - 1-based page numbers
    """
    if total_chapters == 0:
        return (1, total_pages)

    pages_per_chapter = total_pages / total_chapters
    start_page = int(chapter_index * pages_per_chapter) + 1
    end_page = int((chapter_index + 1) * pages_per_chapter)

    # Ensure end_page doesn't exceed total_pages
    if chapter_index == total_chapters - 1:
        end_page = total_pages

    return (start_page, end_page)


def insert_image_references(
    markdown_text: str,
    images: List[Dict[str, any]],
    folder_name: str,
    split_by_chapters: bool = False,
    total_pages: int = None
) -> str:
    """
    Insert image references into markdown text.

    Args:
        markdown_text: Original markdown text
        images: List of image metadata dicts
        folder_name: Name of the images folder (for relative paths)
        split_by_chapters: If True, insert images at end of each chapter
        total_pages: Total number of pages in PDF (needed for chapter splitting)

    Returns:
        Markdown text with image references inserted
    """
    if not images:
        return markdown_text

    if not split_by_chapters:
        # Original behaviour: append all images at end
        image_section = "\n\n## Extracted Images\n\n"

        for img in images:
            # Relative path to image
            img_path = f"{folder_name}/{img['filename']}"

            # Create markdown image reference with source info
            alt_text = f"Image {img['page']}-{img['index']}"
            image_ref = f"![{alt_text}]({img_path})  \n"
            image_ref += f"*Extracted from page {img['page']}*\n\n"

            image_section += image_ref

        # Append image section to the end of the document
        return markdown_text + image_section

    # Split by chapters
    chapters = detect_chapters(markdown_text)
    total_chapters = len(chapters)

    if total_pages is None:
        # If no total_pages provided, fall back to non-split behaviour
        return insert_image_references(markdown_text, images, folder_name, split_by_chapters=False)

    result_parts = []

    for chapter_idx, chapter in enumerate(chapters):
        # Get page range for this chapter
        start_page, end_page = get_page_range_for_chapter(chapter_idx, total_chapters, total_pages)

        # Find images that belong to this chapter
        chapter_images = [img for img in images if start_page <= img['page'] <= end_page]

        # Add chapter content
        result_parts.append(chapter['content'])

        # Add images section if there are any
        if chapter_images:
            image_section = "\n\n### Images for this Chapter\n\n"

            for img in chapter_images:
                # Relative path to image
                img_path = f"{folder_name}/{img['filename']}"

                # Create markdown image reference with source info
                alt_text = f"Image {img['page']}-{img['index']}"
                image_ref = f"![{alt_text}]({img_path})  \n"
                image_ref += f"*Extracted from page {img['page']}*\n\n"

                image_section += image_ref

            result_parts.append(image_section)

        # Add separator between chapters (except for last chapter)
        if chapter_idx < total_chapters - 1:
            result_parts.append("\n\n")

    return ''.join(result_parts)


def split_markdown_by_chapters(
    markdown_text: str,
    output_base_path: str,
    images: List[Dict[str, any]],
    folder_name: str,
    total_pages: int = None
) -> List[str]:
    """
    Split markdown into separate files by chapter.

    Args:
        markdown_text: Markdown content with images already inserted
        output_base_path: Base path for output files (without extension)
        images: List of image metadata dicts (not used, kept for compatibility)
        folder_name: Name of the images folder (not used, kept for compatibility)
        total_pages: Total number of pages in PDF (not used, kept for compatibility)

    Returns:
        List of created file paths
    """
    chapters = detect_chapters(markdown_text)
    created_files = []

    # Get directory and base filename
    output_dir = os.path.dirname(output_base_path)
    base_filename = os.path.basename(output_base_path)
    if base_filename.endswith('.md'):
        base_filename = base_filename[:-3]

    for chapter_idx, chapter in enumerate(chapters):
        # Create chapter filename
        chapter_num = chapter_idx + 1
        # Sanitize chapter title for filename
        safe_title = "".join(c for c in chapter['title'] if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = safe_title.replace(' ', '-')[:50]  # Limit length
        chapter_filename = f"{base_filename}_chapter{chapter_num:02d}_{safe_title}.md"
        chapter_path = os.path.join(output_dir, chapter_filename)

        # Write chapter file (content already has images if they were inserted)
        with open(chapter_path, 'w', encoding='utf-8') as f:
            f.write(chapter['content'])

        created_files.append(chapter_path)

    return created_files
