import sys
import os
import argparse
import warnings

# Suppress pydub runtime warning about missing ffmpeg
warnings.filterwarnings("ignore", message="Couldn't find ffmpeg or avconv")

from markitdown import MarkItDown
import text_processor


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description='Convert files to Markdown with optional image extraction from PDFs.'
    )
    parser.add_argument('input_path', help='Path to the input file')
    parser.add_argument('output_path', nargs='?', help='Path to the output Markdown file (optional, defaults to stdout)')
    parser.add_argument('--extract-images', action='store_true',
                        help='Extract images from PDF files (requires output file)')
    parser.add_argument('--split-chapters', action='store_true',
                        help='Split output into separate files by chapter (H1 headers)')
    parser.add_argument('--clean', action='store_true',
                        help='Clean up broken sentences and extra whitespace')

    args = parser.parse_args()

    # Validate input file exists
    if not os.path.exists(args.input_path):
        print(f"Error: File '{args.input_path}' not found.", file=sys.stderr)
        sys.exit(1)

    # Check if input is a PDF
    is_pdf = args.input_path.lower().endswith('.pdf')

    # Warn if extract-images is used without output path
    if args.extract_images and not args.output_path:
        print("Warning: --extract-images ignored when outputting to stdout", file=sys.stderr)
        args.extract_images = False

    # Warn if extract-images is used with non-PDF
    if args.extract_images and not is_pdf:
        print("Warning: --extract-images only works with PDF files", file=sys.stderr)
        args.extract_images = False

    # Warn if split-chapters is used without output path
    if args.split_chapters and not args.output_path:
        print("Warning: --split-chapters ignored when outputting to stdout", file=sys.stderr)
        args.split_chapters = False

    # Convert file
    try:
        markdown_text = None
        
        # Try PyMuPDF for PDFs first (better column handling)
        if is_pdf:
            try:
                import pdf_image_extractor
                markdown_text = pdf_image_extractor.extract_text_from_pdf(args.input_path)
            except (ImportError, Exception) as e:
                print(f"Note: PyMuPDF extraction failed or not available ({e}), falling back to MarkItDown.", file=sys.stderr)
        
        # Fallback or non-PDF
        if markdown_text is None:
            md = MarkItDown()
            result = md.convert(args.input_path)
            markdown_text = result.text_content

        # Extract images if requested and conditions are met
        images = []
        output_dir = None
        folder_name = None
        total_pages = None

        if args.extract_images and is_pdf and args.output_path:
            try:
                import pdf_image_extractor

                # Get total page count for chapter splitting
                total_pages = pdf_image_extractor.get_pdf_page_count(args.input_path)

                # Create image folder
                output_dir = pdf_image_extractor.create_image_folder(args.output_path)

                # Extract images
                images = pdf_image_extractor.extract_images_from_pdf(
                    args.input_path,
                    output_dir
                )

                if images:
                    folder_name = os.path.basename(output_dir)
                    print(f"Extracted {len(images)} image(s) to '{output_dir}'")
                else:
                    print("No images found in PDF (or all filtered out)")

            except ImportError:
                print("Warning: PyMuPDF not installed. Skipping image extraction.", file=sys.stderr)
                print("Install with: uv add pymupdf", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Image extraction failed: {e}", file=sys.stderr)

        # Insert image references if images were extracted
        if images and folder_name:
            import pdf_image_extractor
            markdown_text = pdf_image_extractor.insert_image_references(
                markdown_text,
                images,
                folder_name,
                split_by_chapters=args.split_chapters,
                total_pages=total_pages
            )

        # Clean text if requested
        if args.clean:
            print("Cleaning text (fixing broken sentences and whitespace)...")
            markdown_text = text_processor.clean_markdown_text(markdown_text)

        # Write output
        if args.output_path:
            if args.split_chapters:
                # Split into separate chapter files
                try:
                    import pdf_image_extractor
                    created_files = pdf_image_extractor.split_markdown_by_chapters(
                        markdown_text,
                        args.output_path,
                        images,
                        folder_name or '',
                        total_pages=total_pages
                    )
                    print(f"Successfully split '{args.input_path}' into {len(created_files)} chapter file(s):")
                    for filepath in created_files:
                        print(f"  - {os.path.basename(filepath)}")
                except Exception as e:
                    print(f"Warning: Chapter splitting failed: {e}", file=sys.stderr)
                    # Fall back to writing single file
                    with open(args.output_path, 'w', encoding='utf-8') as f:
                        f.write(markdown_text)
                    print(f"Successfully converted '{args.input_path}' to '{args.output_path}'")
            else:
                # Write single markdown file
                with open(args.output_path, 'w', encoding='utf-8') as f:
                    f.write(markdown_text)
                print(f"Successfully converted '{args.input_path}' to '{args.output_path}'")
        else:
            print(markdown_text)

    except Exception as e:
        print(f"Error converting file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
