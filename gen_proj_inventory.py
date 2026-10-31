import os
import re
import subprocess
import json
import glob
import csv
import datetime

roots = ['/home/pi/WebApps', '/home/pi/WebApps/Tools', '/var/www/html']
projects = {}

def get_size(path):
    try:
        # Use du -sh to get human readable size
        result = subprocess.check_output(['du', '-sh', path], stderr=subprocess.DEVNULL)
        return result.split()[0].decode('utf-8')
    except:
        return "N/A"

def get_description(path):
    readme_path = os.path.join(path, 'README.md')
    if not os.path.exists(readme_path):
        return ""
    
    try:
        with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            for line in lines:
                line = line.strip()
                # Skip headers, empty lines, and badges/images
                if not line or line.startswith('#') or line.startswith('![') or line.startswith('[!'):
                    continue
                # Return the first meaningful line, truncated
                desc = line[:100] + "..." if len(line) > 100 else line
                return desc
    except:
        return ""
    return ""

def get_test_info(path):
    tests = []
    
    # Check package.json for test scripts
    pkg_json_path = os.path.join(path, 'package.json')
    if os.path.exists(pkg_json_path):
        try:
            with open(pkg_json_path, 'r') as f:
                data = json.load(f)
                if 'scripts' in data and 'test' in data['scripts']:
                    test_cmd = data['scripts']['test']
                    if "no test specified" not in test_cmd.lower():
                        tests.append(f'`{test_cmd}`')
        except:
            pass

    # Check for Python test frameworks in requirements.txt or files
    req_path = os.path.join(path, 'requirements.txt')
    if os.path.exists(req_path):
        try:
            with open(req_path, 'r') as f:
                content = f.read().lower()
                if 'pytest' in content:
                    tests.append("Pytest")
                elif 'unittest' in content:
                    tests.append("Unittest")
        except:
            pass
            
    # Check for test directories
    for d in ['test', 'tests', '__tests__', 'spec']:
        if os.path.isdir(os.path.join(path, d)):
            tests.append(f"Dir: `{d}/`")
            break # Just report the first one found to save space

    if not tests:
        return ""
    
    return ", ".join(tests)

def get_services():
    """
    Scans /etc/systemd/system/ for services.
    Returns: { working_dir_path: {'name': service_name, 'active': bool} }
    """
    services = {}
    service_dir = '/etc/systemd/system'
    
    try:
        files = glob.glob(os.path.join(service_dir, '*.service'))
    except:
        return services

    for service_file in files:
        service_name = os.path.basename(service_file)
        try:
            with open(service_file, 'r', errors='ignore') as f:
                content = f.read()
            match = re.search(r'WorkingDirectory=(.*)', content)
            if match:
                wd = match.group(1).strip()
                wd = os.path.realpath(wd) 
                is_active = False
                try:
                    status = subprocess.check_output(['systemctl', 'is-active', service_name], stderr=subprocess.DEVNULL)
                    if status.strip() == b'active':
                        is_active = True
                except:
                    pass
                services[wd] = {'name': service_name, 'active': is_active}
        except:
            continue
    return services

def get_nginx_mapping():
    """
    Scans /etc/nginx/sites-enabled/ for URL mappings.
    Returns: { path: url }
    """
    mapping = {}
    nginx_dir = '/etc/nginx/sites-enabled'
    
    try:
        files = glob.glob(os.path.join(nginx_dir, '*'))
    except:
        return mapping
        
    for conf_file in files:
        try:
            with open(conf_file, 'r', errors='ignore') as f:
                content = f.read()
            server_name_match = re.search(r'server_name\s+(.*?);', content)
            if not server_name_match:
                continue
            domain = server_name_match.group(1).split()[0]
            if 'drawingtable.net' in server_name_match.group(1):
                 for d in server_name_match.group(1).split():
                     if 'drawingtable.net' in d:
                         domain = d
                         break
            base_url = f"https://{domain}"
            locations = re.finditer(r'location\s+([^{]+)\s+\{([^}]+)\}', content, re.DOTALL)
            for loc in locations:
                path_route = loc.group(1).strip()
                block = loc.group(2)
                fs_path = None
                if 'alias' in block:
                    alias_match = re.search(r'alias\s+(.*?);', block)
                    if alias_match:
                        fs_path = alias_match.group(1).strip()
                elif 'root' in block:
                    root_match = re.search(r'root\s+(.*?);', block)
                    if root_match:
                        fs_path = root_match.group(1).strip()
                if fs_path:
                    real_fs_path = os.path.realpath(fs_path)
                    if path_route.endswith('/static/') and real_fs_path.endswith('/static'):
                         clean_route = path_route.replace('/static/', '/')
                         clean_fs = os.path.dirname(real_fs_path) 
                         mapping[clean_fs] = f"{base_url}{clean_route}"
                    else:
                        mapping[real_fs_path] = f"{base_url}{path_route}"
        except:
            continue
    return mapping

def get_github_issue_count(remote):
    """Get the number of open issues for a GitHub remote.
    Returns the count as an int, or None if not a GitHub repo."""
    if 'github.com' not in remote:
        return None
    # Extract owner/repo from SSH or HTTPS remote URLs
    match = re.search(r'[:/]([^/]+/[^/]+?)(?:\.git)?$', remote)
    if not match:
        return None
    repo = match.group(1)
    try:
        result = subprocess.check_output(
            ['gh', 'api', f'repos/{repo}', '--jq', '.open_issues_count'],
            stderr=subprocess.DEVNULL, timeout=10
        )
        return int(result.strip())
    except Exception:
        return None


def get_visibility_info():
    """
    Determines project visibility based on filelist.json and updatehtmls.py.
    Returns: (linked_set, hidden_set)
    """
    html_dir = '/home/pi/WebApps/html'
    filelist_path = os.path.join(html_dir, 'filelist.json')
    update_script_path = os.path.join(html_dir, 'updatehtmls.py')
    
    linked = set()
    hidden = set()
    
    if os.path.exists(filelist_path):
        try:
            with open(filelist_path, 'r') as f:
                data = json.load(f)
            def extract_keys(structure):
                for item in structure:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            linked.add(k)
                            if isinstance(v, list):
                                extract_keys(v)
            extract_keys(data)
        except:
            pass

    if os.path.exists(update_script_path):
        try:
            with open(update_script_path, 'r') as f:
                content = f.read()
            match = re.search(r'default_excluded\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if match:
                raw_list = match.group(1)
                hidden = set(re.findall(r'["\'](.*?)["\']', raw_list))
        except:
            pass
            
    return linked, hidden

# --- Main Execution ---

services = get_services()
nginx_urls = get_nginx_mapping()
linked_projects, hidden_projects = get_visibility_info()

matched_services = set()

for root in roots:
    if not os.path.exists(root):
        continue
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
            
        real_path = os.path.realpath(path)
        
        if real_path in projects:
            if path not in projects[real_path]['locations']:
                projects[real_path]['locations'].append(path)
            continue
            
        has_git = os.path.exists(os.path.join(real_path, '.git'))
        remote = "None"
        owner = "N/A"
        
        if has_git:
            try:
                config_path = os.path.join(real_path, '.git', 'config')
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        content = f.read()
                        match = re.search(r'url\s*=\s*(.+)', content)
                        if match:
                            remote = match.group(1).strip()
            except Exception as e:
                remote = f"Error: {e}"
        
        if 'github.com-wta' in remote or 'alastairWTA' in remote:
            owner = "WTA (Work)"
        elif 'github.com-personal' in remote or 'Al4st41r' in remote or 'alastairogle' in remote:
            owner = "Personal"
        elif remote != "None":
            owner = "Other"
            
        size = get_size(real_path)
        description = get_description(real_path)
        tests = get_test_info(real_path)
        issues = get_github_issue_count(remote)
        
        # Match Service
        service_info = services.get(real_path)
        service_str = "N/A"
        if service_info:
            icon = "🟢" if service_info['active'] else "🔴"
            service_str = f"{icon} {service_info['name']}"
            matched_services.add(real_path)
        
        # Match URL
        url = "N/A"
        if real_path in nginx_urls:
            url = nginx_urls[real_path]
        elif path in nginx_urls:
            url = nginx_urls[path]
        elif '/var/www/html' in path:
             base_name = os.path.basename(path)
             url = f"https://architools.drawingtable.net/{base_name}/"
             
        # Determine Visibility
        visibility = "N/A"
        
        is_in_html = any('/var/www/html' in loc for loc in [path])
        
        if name in linked_projects:
            visibility = "🟢 Visible"
        elif name in hidden_projects:
            visibility = "🙈 Hidden"
        elif service_info:
            visibility = "⚙️ Service"
        elif is_in_html or os.path.exists(os.path.join('/var/www/html', name)):
            visibility = "⚪ Unlisted"

        projects[real_path] = {
            'name': name,
            'locations': [path],
            'has_git': has_git,
            'remote': remote,
            'owner': owner,
            'size': size,
            'description': description,
            'tests': tests,
            'service': service_str,
            'url': url,
            'visibility': visibility,
            'issues': issues
        }

# Post-process to consolidate locations and ensure URL correctness based on all locations
for p in projects.values():
    if p['url'] == "N/A":
        for loc in p['locations']:
             if '/var/www/html' in loc:
                 folder_name = os.path.basename(loc)
                 p['url'] = f"https://architools.drawingtable.net/{folder_name}/"
                 break
    
    if p['visibility'] == "N/A":
         if p['name'] in linked_projects:
             p['visibility'] = "🟢 Visible"
         elif p['name'] in hidden_projects:
             p['visibility'] = "🙈 Hidden"
         elif "🟢" in p['service'] or "🔴" in p['service']:
             p['visibility'] = "⚙️ Service"
         elif any('/var/www/html' in loc for loc in p['locations']):
             p['visibility'] = "⚪ Unlisted"

print("# Project Inventory")

print("\nThis file provides an overview of the projects located in `~/WebApps/` and `/var/www/html/`.")
print("\n**Legend:**")
print("- Service: 🟢 Active, 🔴 Inactive")
print("- Visibility: 🟢 Visible (Linked in Index), 🙈 Hidden (Explicitly Excluded), ⚙️ Service (Backend App), ⚪ Unlisted (Exists in HTML but not linked)")

print("\n## Inventory Table\n")

print("| Project Name | Description | Issues | Tests | Service | Visibility | URL | Location(s) | Size | Git | Owner | Remote URL |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")

sorted_projects = sorted(projects.values(), key=lambda x: x['name'].lower())

for p in sorted_projects:
    locs = "<br>".join(p['locations'])
    git_status = "✅" if p['has_git'] else "❌"
    url_link = f"[{p['url']}]({p['url']})" if p['url'] != "N/A" else "N/A"
    issues_str = str(p['issues']) if p['issues'] is not None else ""
    print(f"| {p['name']} | {p['description']} | {issues_str} | {p['tests']} | {p['service']} | {p['visibility']} | {url_link} | {locs} | {p['size']} | {git_status} | {p['owner']} | {p['remote']} |")

# --- Unmatched Services Section ---
print("\n## Unmatched Services")
print("These systemd services were detected but not mapped to any project in the main inventory (likely due to path mismatches).")
print("\n| Service Name | Status | Working Directory |")
print("|---|---|---|")

for wd, s in services.items():
    if wd not in matched_services:
        icon = "🟢" if s['active'] else "🔴"
        print(f"| {s['name']} | {icon} | `{wd}` |")

print("\n## Maintenance")

print("\nYou can update this file by running the script located at:")
print("`~/WebApps/Tools/gen_proj_inventory.py`\n")
print("Usage:")
print("```bash")
print("python3 ~/WebApps/Tools/gen_proj_inventory.py > ~/WebApps/Tools/project_inventory.md")
print("```")

# --- Generate CSV ---
csv_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'project_inventory.csv')
with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
    fieldnames = ['Project Name', 'Description', 'Open Issues', 'Tests', 'Service', 'Visibility', 'URL', 'Locations', 'Size', 'Git', 'Owner', 'Remote URL']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

    writer.writeheader()
    for p in sorted_projects:
        locs_csv = ", ".join(p['locations'])
        git_csv = "Yes" if p['has_git'] else "No"
        
        writer.writerow({
            'Project Name': p['name'],
            'Description': p['description'],
            'Open Issues': p['issues'] if p['issues'] is not None else '',
            'Tests': p['tests'],
            'Service': p['service'].replace('🟢 ', '').replace('🔴 ', ''), 
            'Visibility': p['visibility'].replace('🟢 ', '').replace('🙈 ', '').replace('⚙️ ', '').replace('⚪ ', ''),
            'URL': p['url'],
            'Locations': locs_csv,
            'Size': p['size'],
            'Git': git_csv,
            'Owner': p['owner'],
            'Remote URL': p['remote']
        })

# --- Generate JSON ---
json_data = {
    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "total_projects": len(sorted_projects),
    "projects": [],
    "unmatched_services": []
}

for p in sorted_projects:
    service_clean = p['service'].replace('🟢 ', '').replace('🔴 ', '')
    service_active = '🟢' in p['service']
    visibility_clean = p['visibility'].replace('🟢 ', '').replace('🙈 ', '').replace('⚙️ ', '').replace('⚪ ', '')
    
    json_data["projects"].append({
        "name": p['name'],
        "description": p['description'],
        "open_issues": p['issues'],
        "tests": p['tests'],
        "service": service_clean if service_clean != "N/A" else None,
        "service_active": service_active,
        "visibility": visibility_clean,
        "url": p['url'] if p['url'] != "N/A" else None,
        "locations": p['locations'],
        "size": p['size'],
        "has_git": p['has_git'],
        "owner": p['owner'] if p['owner'] != "N/A" else None,
        "remote_url": p['remote'] if p['remote'] != "None" else None
    })

for wd, s in services.items():
    if wd not in matched_services:
        json_data["unmatched_services"].append({
            "name": s['name'],
            "active": s['active'],
            "working_directory": wd
        })

json_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'project_inventory.json')
with open(json_path, 'w', encoding='utf-8') as jsonfile:
    json.dump(json_data, jsonfile, indent=2)

inventory_web_dir = '/home/pi/WebApps/inventory'
if os.path.exists(inventory_web_dir):
    web_json_path = os.path.join(inventory_web_dir, 'project_inventory.json')
    with open(web_json_path, 'w', encoding='utf-8') as jsonfile:
        json.dump(json_data, jsonfile, indent=2)

