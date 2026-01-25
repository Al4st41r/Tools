// PDF to Markdown Web App JavaScript

let selectedFile = null;

// Initialise when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeUploadZone();
});

function initializeUploadZone() {
    const uploadZone = document.getElementById('uploadZone');
    const fileInput = document.getElementById('fileInput');
    const processBtn = document.getElementById('processBtn');

    // Click to select file
    uploadZone.addEventListener('click', () => {
        fileInput.click();
    });

    // File input change
    fileInput.addEventListener('change', (e) => {
        handleFileSelect(e.target.files[0]);
    });

    // Drag and drop handlers
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.add('drag-over');
    });

    uploadZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.remove('drag-over');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.remove('drag-over');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileSelect(files[0]);
        }
    });

    // Process button
    processBtn.addEventListener('click', () => {
        if (selectedFile) {
            processFile(selectedFile);
        }
    });
}

function handleFileSelect(file) {
    // Validate file type
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showError('Invalid file type. Please select a PDF file (.pdf)');
        return;
    }

    selectedFile = file;

    // Hide upload zone, show file info
    document.getElementById('uploadSection').style.display = 'none';
    document.getElementById('fileInfoSection').style.display = 'block';

    // Display file details
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileSize').textContent = formatFileSize(file.size);
}

function removeFile() {
    selectedFile = null;
    document.getElementById('fileInput').value = '';
    document.getElementById('uploadSection').style.display = 'block';
    document.getElementById('fileInfoSection').style.display = 'none';
    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('resultSection').style.display = 'none';
    document.getElementById('errorSection').style.display = 'none';
}

async function processFile(file) {
    // Get checkbox states
    const extractImages = document.getElementById('extractImagesCheckbox').checked;
    const splitChapters = document.getElementById('splitChaptersCheckbox').checked;
    const cleanText = document.getElementById('cleanTextCheckbox').checked;

    // Hide file info, show progress
    document.getElementById('fileInfoSection').style.display = 'none';
    document.getElementById('progressSection').style.display = 'block';
    document.getElementById('resultSection').style.display = 'none';
    document.getElementById('errorSection').style.display = 'none';

    // Update progress
    updateProgress(10, 'Uploading PDF file...');

    try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('extract_images', extractImages);
        formData.append('split_chapters', splitChapters);
        formData.append('clean_text', cleanText);

        const xhr = new XMLHttpRequest();

        // Track upload progress
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percentComplete = Math.round((e.loaded / e.total) * 30); // 0-30%
                updateProgress(percentComplete, 'Uploading PDF file...');
            }
        });

        // Handle response
        xhr.addEventListener('load', () => {
            if (xhr.status === 200) {
                const response = JSON.parse(xhr.responseText);
                if (response.success) {
                    handleSuccess(response);
                } else {
                    handleError(response.error || 'Unknown error occurred');
                }
            } else {
                const errorResponse = JSON.parse(xhr.responseText);
                handleError(errorResponse.error || `Server error: ${xhr.status}`);
            }
        });

        xhr.addEventListener('error', () => {
            handleError('Network error. Please check your connection.');
        });

        xhr.addEventListener('timeout', () => {
            handleError('Request timeout. The file may be too large or the server is busy.');
        });

        // Simulate processing stages
        updateProgress(35, 'Converting PDF to text...');
        await sleep(500);

        if (extractImages) {
            updateProgress(50, 'Extracting images from PDF...');
            await sleep(500);
            updateProgress(70, 'Creating output archive...');
        } else {
            updateProgress(60, 'Generating Markdown...');
        }

        xhr.timeout = 600000; // 10 minutes timeout for large files
        xhr.open('POST', '/pdf2markdown/upload', true);
        xhr.send(formData);

    } catch (error) {
        handleError(`Error: ${error.message}`);
    }
}

function handleSuccess(response) {
    updateProgress(100, 'Complete!');

    setTimeout(() => {
        document.getElementById('progressSection').style.display = 'none';
        document.getElementById('resultSection').style.display = 'block';

        document.getElementById('resultFileName').textContent = response.original_filename;
        document.getElementById('resultTime').textContent = response.processing_time;

        // Update result type message
        let resultType = '';
        if (response.has_chapters && response.has_images) {
            resultType = `Your document has been split into ${response.chapter_count} chapter files with extracted images, packaged into a ZIP archive.`;
        } else if (response.has_chapters) {
            resultType = `Your document has been split into ${response.chapter_count} chapter files, packaged into a ZIP archive.`;
        } else if (response.has_images) {
            resultType = 'Your Markdown file and extracted images have been packaged into a ZIP archive.';
        } else {
            resultType = 'Your Markdown file is ready for download.';
        }
        document.getElementById('resultType').textContent = resultType;

        // Set up download button
        const downloadBtn = document.getElementById('downloadBtn');
        const isZip = response.has_images || response.has_chapters;
        downloadBtn.textContent = isZip ? 'Download ZIP Archive' : 'Download Markdown File';
        downloadBtn.onclick = () => {
            window.location.href = `/pdf2markdown/download/${response.download_filename}`;
        };
    }, 500);
}

function handleError(errorMessage) {
    document.getElementById('progressSection').style.display = 'none';
    document.getElementById('errorSection').style.display = 'block';
    document.getElementById('errorMessage').textContent = errorMessage;
}

function updateProgress(percent, status) {
    const progressFill = document.getElementById('progressFill');
    const progressStatus = document.getElementById('progressStatus');

    progressFill.style.width = `${percent}%`;
    progressFill.textContent = `${percent}%`;
    progressStatus.textContent = status;
}

function showError(message) {
    alert(message);
}

function resetUpload() {
    removeFile();
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Hamburger menu toggle
function toggleMenu() {
    const navMenu = document.getElementById('navMenu');
    navMenu.classList.toggle('active');
}

// Close menu when clicking outside
document.addEventListener('click', function(event) {
    const navMenu = document.getElementById('navMenu');
    const hamburger = document.querySelector('.hamburger');

    if (navMenu && hamburger) {
        if (!navMenu.contains(event.target) && !hamburger.contains(event.target)) {
            navMenu.classList.remove('active');
        }
    }
});
