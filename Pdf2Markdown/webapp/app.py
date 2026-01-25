#!/usr/bin/env python3
"""
PDF to Markdown Web Application
Flask server for converting PDF files to Markdown with optional image extraction
"""

from flask import Flask, render_template, request, send_file, jsonify
import os
import sys
import subprocess
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import uuid
import traceback
from datetime import datetime
import threading
import time
import zipfile
import shutil

app = Flask(__name__)

# Configure for running behind nginx reverse proxy with URL prefix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config['APPLICATION_ROOT'] = '/pdf2markdown'

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['OUTPUT_FOLDER'] = os.path.join(os.path.dirname(__file__), 'outputs')

# Path to main Pdf2Markdown project directory
PDF2MD_ROOT = os.path.dirname(os.path.dirname(__file__))

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_old_files(directory, max_age_seconds=3600):
    """Remove files older than max_age_seconds from directory"""
    try:
        now = time.time()
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                file_age = now - os.path.getmtime(filepath)
                if file_age > max_age_seconds:
                    os.remove(filepath)
                    print(f"Cleaned up old file: {filename}")
            elif os.path.isdir(filepath):
                # Clean up old directories (image folders)
                dir_age = now - os.path.getmtime(filepath)
                if dir_age > max_age_seconds:
                    shutil.rmtree(filepath)
                    print(f"Cleaned up old directory: {filename}")
    except Exception as e:
        print(f"Error during cleanup: {e}")

def schedule_cleanup(path, delay=300):
    """Schedule file or directory deletion after delay seconds"""
    def delete_path():
        time.sleep(delay)
        try:
            if os.path.exists(path):
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
                print(f"Deleted temporary path: {path}")
        except Exception as e:
            print(f"Error deleting path {path}: {e}")

    thread = threading.Thread(target=delete_path, daemon=True)
    thread.start()

def create_zip(md_path, images_dir, zip_path, chapter_files=None):
    """Create ZIP file containing markdown and images"""
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add markdown file(s) to root of zip
        if chapter_files and len(chapter_files) > 0:
            # Add all chapter files
            for chapter_path in chapter_files:
                if os.path.exists(chapter_path):
                    zipf.write(chapter_path, os.path.basename(chapter_path))
        else:
            # Add single markdown file
            if os.path.exists(md_path):
                zipf.write(md_path, os.path.basename(md_path))

        # Add images directory if it exists
        if os.path.exists(images_dir) and os.path.isdir(images_dir):
            for root, dirs, files in os.walk(images_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.join(os.path.basename(images_dir), file)
                    zipf.write(file_path, arcname)

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle PDF file upload and processing"""

    # Clean up old files before processing
    cleanup_old_files(app.config['UPLOAD_FOLDER'], max_age_seconds=3600)
    cleanup_old_files(app.config['OUTPUT_FOLDER'], max_age_seconds=3600)

    # Check if file is present in request
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    # Check if file was selected
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Validate file type
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Only .pdf files are allowed'}), 400

    # Get flags from form data
    extract_images = request.form.get('extract_images') == 'true'
    split_chapters = request.form.get('split_chapters') == 'true'
    clean_text = request.form.get('clean_text') == 'true'

    try:
        # Generate unique filename to avoid collisions
        unique_id = str(uuid.uuid4())
        original_filename = secure_filename(file.filename)
        pdf_filename = f"{unique_id}_{original_filename}"
        md_basename = os.path.splitext(original_filename)[0]
        md_filename = f"{unique_id}_{md_basename}.md"

        # Save paths
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename)
        md_path = os.path.join(app.config['OUTPUT_FOLDER'], md_filename)

        # Save uploaded file
        file.save(pdf_path)
        file_size = os.path.getsize(pdf_path)
        print(f"Received PDF file: {original_filename} ({file_size / 1024 / 1024:.2f} MB)")

        # Process the PDF file
        print(f"Starting PDF to Markdown conversion for {original_filename}")
        print(f"Extract images: {extract_images}")
        print(f"Split chapters: {split_chapters}")
        print(f"Clean text: {clean_text}")
        start_time = datetime.now()

        # Build command
        cmd = ['uv', 'run', 'main.py', pdf_path, md_path]
        if extract_images:
            cmd.append('--extract-images')
        if split_chapters:
            cmd.append('--split-chapters')
        if clean_text:
            cmd.append('--clean')

        # Run conversion
        result = subprocess.run(
            cmd,
            cwd=PDF2MD_ROOT,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )

        if result.returncode != 0:
            raise Exception(f"Conversion failed: {result.stderr}")

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"Conversion completed in {duration:.2f} seconds")
        print(f"Output: {result.stdout}")

        # Check if images were extracted
        images_dir = os.path.join(app.config['OUTPUT_FOLDER'], f"{unique_id}_{md_basename}_images")
        has_images = os.path.exists(images_dir) and os.path.isdir(images_dir)

        # Find chapter files if split_chapters was used
        chapter_files = []
        if split_chapters:
            # Look for chapter files with pattern: {unique_id}_{md_basename}_chapter*.md
            pattern = os.path.join(app.config['OUTPUT_FOLDER'], f"{unique_id}_{md_basename}_chapter*.md")
            import glob
            chapter_files = glob.glob(pattern)
            print(f"Found {len(chapter_files)} chapter files")

        download_filename = None
        files_to_cleanup = [pdf_path]

        # Determine what to package
        if chapter_files or has_images:
            # Create ZIP file containing markdown and/or images
            zip_filename = f"{unique_id}_pdf2markdown_output.zip"
            zip_path = os.path.join(app.config['OUTPUT_FOLDER'], zip_filename)

            create_zip(md_path, images_dir, zip_path, chapter_files=chapter_files)
            download_filename = zip_filename
            files_to_cleanup.extend([zip_path, images_dir] + chapter_files)
            if not chapter_files:
                # If no chapter files, also clean up main md file
                files_to_cleanup.append(md_path)

            print(f"Created ZIP archive: {zip_filename}")
        else:
            # Just markdown file
            download_filename = md_filename
            files_to_cleanup.append(md_path)

        # Schedule cleanup of all files after 5 minutes
        for path in files_to_cleanup:
            schedule_cleanup(path, delay=300)

        # Return success with download filename
        return jsonify({
            'success': True,
            'message': f'Successfully processed {original_filename}',
            'download_filename': download_filename,
            'processing_time': f"{duration:.2f}",
            'original_filename': original_filename,
            'has_images': has_images,
            'has_chapters': len(chapter_files) > 0,
            'chapter_count': len(chapter_files),
            'file_type': 'zip' if (chapter_files or has_images) else 'markdown'
        })

    except subprocess.TimeoutExpired:
        # Clean up on timeout
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        return jsonify({
            'error': 'Processing timeout. PDF file may be too large or complex.'
        }), 500

    except Exception as e:
        # Clean up files on error
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if 'md_path' in locals() and os.path.exists(md_path):
            os.remove(md_path)
        if 'images_dir' in locals() and os.path.exists(images_dir):
            shutil.rmtree(images_dir)
        if 'zip_path' in locals() and os.path.exists(zip_path):
            os.remove(zip_path)

        error_msg = str(e)
        traceback.print_exc()
        return jsonify({
            'error': f'Error processing PDF file: {error_msg}'
        }), 500

@app.route('/download/<filename>')
def download_file(filename):
    """Download the processed markdown or ZIP file"""
    try:
        # Security: validate filename pattern
        secure_name = secure_filename(filename)
        filepath = os.path.join(app.config['OUTPUT_FOLDER'], secure_name)

        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found or expired'}), 404

        # Determine MIME type and download name
        # Strip the UUID prefix (first 36 chars + underscore = 37) to get original name
        if len(filename) > 37 and filename[8] == '-' and filename[13] == '-' and filename[18] == '-' and filename[23] == '-':
            original_display_name = filename[37:]
        else:
            original_display_name = filename

        if filename.endswith('.zip'):
            mimetype = 'application/zip'
            download_name = original_display_name
        elif filename.endswith('.md'):
            mimetype = 'text/markdown'
            download_name = original_display_name
        else:
            return jsonify({'error': 'Invalid file type'}), 400

        return send_file(
            filepath,
            as_attachment=True,
            download_name=download_name,
            mimetype=mimetype
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'Error downloading file: {str(e)}'}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    # Ensure directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

    # Run Flask app
    app.run(host='127.0.0.1', port=5002, debug=False)
