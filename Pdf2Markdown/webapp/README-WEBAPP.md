# PDF to Markdown Web Application

## Overview
Web interface for converting PDF files to Markdown format with optional image extraction. Built with Flask and deployed behind nginx reverse proxy.

## Live URL
https://architools.drawingtable.net/pdf2markdown/

## Architecture
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Backend**: Flask 3.0 (Python 3.13)
- **Design System**: Architools v2.0 (flat design, no rounded corners)
- **Reverse Proxy**: Nginx
- **Process Manager**: systemd

## File Structure
```
webapp/
├── app.py                    # Flask application
├── templates/
│   └── index.html           # Single-page interface
├── static/
│   ├── css/
│   │   ├── ao-styles.css   # Architools design system
│   │   └── app.css         # Custom styles
│   └── js/
│       └── app.js          # Frontend JavaScript
├── uploads/                 # Temporary PDF storage
├── outputs/                 # Temporary markdown/ZIP storage
├── logs/                    # Application logs
├── pdf2markdown.service    # Systemd service file
├── nginx-config-snippet.txt # Nginx configuration
├── requirements.txt        # Python dependencies
└── README-WEBAPP.md        # This file
```

## Features
- Drag-and-drop PDF upload
- Optional image extraction with checkbox
- Automatic filtering of small images (< 100×100px)
- ZIP archive creation when images are extracted
- Real-time progress tracking
- Large file support (up to 500MB)
- 10-minute timeout for complex PDFs
- Automatic file cleanup after 5 minutes

## Configuration

### Flask App (app.py)
- **Port**: 5002
- **Host**: 127.0.0.1 (localhost only)
- **Max Upload Size**: 500MB
- **Allowed Extensions**: .pdf
- **APPLICATION_ROOT**: /pdf2markdown

### Nginx Reverse Proxy
Location: `/etc/nginx/sites-available/architools.conf`

```nginx
location /pdf2markdown/ {
    proxy_pass http://127.0.0.1:5002/;
    # Proxy headers and timeouts configured for large files
    client_max_body_size 500M;
}
```

### Systemd Service
Service file: `/etc/systemd/system/pdf2markdown.service`

Configuration:
- **User**: pi
- **WorkingDirectory**: /home/pi/WebApps/Pdf2Markdown/webapp
- **Virtual Environment**: /home/pi/WebApps/Pdf2Markdown/.venv
- **Auto-restart**: Yes (10-second delay)
- **Logging**: app.log and error.log

## Management Commands

### Service Management
```bash
# Start service
sudo systemctl start pdf2markdown

# Stop service
sudo systemctl stop pdf2markdown

# Restart service
sudo systemctl restart pdf2markdown

# Check status
sudo systemctl status pdf2markdown

# Enable auto-start on boot
sudo systemctl enable pdf2markdown

# Disable auto-start
sudo systemctl disable pdf2markdown
```

### Log Management
```bash
# View application logs
tail -f logs/app.log

# View error logs
tail -f logs/error.log

# View systemd journal
sudo journalctl -u pdf2markdown -f
```

### Nginx Management
```bash
# Test nginx configuration
sudo nginx -t

# Reload nginx
sudo nginx -s reload

# View nginx error log
sudo tail -f /var/log/nginx/error.log
```

## Deployment

### Initial Setup
1. Create directory structure
2. Install dependencies: `uv sync`
3. Create systemd service: `sudo cp pdf2markdown.service /etc/systemd/system/`
4. Enable service: `sudo systemctl enable pdf2markdown`
5. Start service: `sudo systemctl start pdf2markdown`
6. Update nginx configuration
7. Test nginx: `sudo nginx -t`
8. Reload nginx: `sudo nginx -s reload`

### Updating the Application
```bash
# 1. Stop the service
sudo systemctl stop pdf2markdown

# 2. Update code files (app.py, templates, static, etc.)

# 3. Restart the service
sudo systemctl start pdf2markdown

# 4. Check status
sudo systemctl status pdf2markdown
```

### Updating Static Files Only
Static files (CSS/JS) are served directly by nginx with 1-year cache expiry.
After updating static files, users may need to hard-refresh (Ctrl+F5) to see changes.

## Troubleshooting

### Service Won't Start
```bash
# Check service status
sudo systemctl status pdf2markdown

# Check error logs
tail -n 50 logs/error.log

# Check if port 5002 is in use
sudo netstat -tlnp | grep 5002

# Manually test Flask app
cd /home/pi/WebApps/Pdf2Markdown/webapp
/home/pi/WebApps/Pdf2Markdown/.venv/bin/python3 app.py
```

### 404 Errors
```bash
# Check nginx configuration
sudo nginx -t

# Check if location block exists
grep -A 10 "pdf2markdown" /etc/nginx/sites-available/architools.conf

# Check nginx error logs
sudo tail -f /var/log/nginx/error.log
```

### Upload Failures
- Check file size (max 500MB)
- Check disk space: `df -h`
- Check upload directory permissions: `ls -la uploads/`
- Check error logs: `tail -f logs/error.log`

### Timeout Issues
- Large PDFs may take time to process
- Default timeout: 600 seconds (10 minutes)
- Check progress in app.log
- Consider increasing timeout if needed

## Security Considerations
- Files stored with UUID-based names to prevent collisions
- Secure filename validation using Werkzeug
- Automatic file cleanup after 5 minutes
- No privilege escalation (systemd NoNewPrivileges=true)
- Private temporary directory (systemd PrivateTmp=true)
- File type validation (PDF only)
- Size limit enforcement (500MB)

## Performance
- Static files cached for 1 year
- Automatic cleanup of old temporary files (hourly, >1 hour old)
- Gzip compression enabled for text files
- Large file upload support via nginx configuration

## Dependencies
```
Flask==3.0.0
Werkzeug==3.0.0
markitdown[all]>=0.1.4
pymupdf==1.26.7
```

## Version History
- **v1.0** (2025-12-23): Initial deployment
  - PDF to Markdown conversion
  - Optional image extraction
  - ZIP archive creation
  - Web interface with Architools design system

## Support
For issues or questions:
1. Check application logs: `tail -f logs/app.log logs/error.log`
2. Check service status: `sudo systemctl status pdf2markdown`
3. Check nginx logs: `sudo tail -f /var/log/nginx/error.log`
4. Contact development team

## Related Documentation
- Main CLI tool: `/home/pi/WebApps/Pdf2Markdown/README.md`
- Claude skill: `/home/pi/WebApps/Pdf2Markdown/.claude/skills/pdf2markdown/`
- Services registry: `/home/pi/WebApps/services.md`
