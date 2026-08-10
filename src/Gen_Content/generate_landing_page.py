import datetime
import os

from Gen_Content.render_listening import load_listening, render_listening


def generate_landing_page(content_path, template_path, dest_path, site_config=None):
    """
    Generate a landing page that lists all available content pages.
    
    Args:
        content_path: Path to content directory containing .md files
        template_path: Path to titlepage.html template
        dest_path: Destination path for generated index.html
        site_config: Optional dict with site metadata (title, description, author)
    """
    # Default configuration
    config = {
        "title": "Welcome",
        "site_title": "My Portfolio",
        "site_description": "Welcome to my personal site",
        "site_author": "Your Name",
        "description": "Explore my projects, resume, and more"
    }
    if site_config:
        config.update(site_config)
    
    print(f"Generating landing page from {content_path} to {dest_path}")
    
    # Scan content directory for markdown files
    md_files = []
    if os.path.exists(content_path):
        for filename in sorted(os.listdir(content_path)):
            if filename.lower().endswith('.md'):
                md_path = os.path.join(content_path, filename)
                html_name = f"{os.path.splitext(filename)[0]}.html"
                
                # Try to extract title from the markdown file
                try:
                    with open(md_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Check for landing page title override comment
                    page_title = None
                    for line in content.splitlines()[:5]:  # Check first 5 lines
                        if line.strip().startswith('<!-- landing-title:'):
                            # Extract title from comment: <!-- landing-title: Resume -->
                            page_title = line.strip()[19:].strip().removesuffix('-->').strip()
                            break
                    
                    # If no override, use extract_title function
                    if not page_title:
                        try:
                            import sys
                            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
                            from Gen_Content.extract_title_markdown import extract_title
                            page_title = extract_title(content)
                        # Broad on purpose: this is one link in a best-effort
                        # title-extraction chain (import/parse -> heading ->
                        # filename), so any failure here should fall through
                        # rather than be caught by type.
                        except Exception as exc:  # noqa: BLE001
                            print(f"  Note: extract_title failed for {filename}, "
                                  f"falling back to heading/filename: {exc}")
                            # Fallback: look for first # heading
                            for line in content.splitlines():
                                if line.strip().startswith('# '):
                                    page_title = line.strip()[2:].strip()
                                    break
                            else:
                                # Use filename as title
                                page_title = os.path.splitext(filename)[0].replace('_', ' ').replace('-', ' ').title()
                    
                    md_files.append({
                        'filename': filename,
                        'html_name': html_name,
                        'title': page_title
                    })
                except (OSError, UnicodeDecodeError) as e:
                    print(f"Warning: Could not process {filename}: {e}")
                    # Add with filename as title
                    md_files.append({
                        'filename': filename,
                        'html_name': html_name,
                        'title': os.path.splitext(filename)[0].replace('_', ' ').replace('-', ' ').title()
                    })
    
    # Check if dev_diary directory exists and add it as a special link
    dev_diary_path = os.path.join(content_path, 'dev_diary')
    has_dev_diary = os.path.exists(dev_diary_path) and os.path.isdir(dev_diary_path)
    
    # Generate page links HTML
    if md_files or has_dev_diary:
        page_links_html = []
        
        # Presentation lives in landing.css — keep this markup bare.
        # Add Dev Diary first if it exists
        if has_dev_diary:
            page_links_html.append(
                '              <li><a href="dev_diary.html">Dev Diary</a></li>'
            )

        # Add regular pages
        for page in md_files:
            page_links_html.append(
                f'              <li><a href="{page["html_name"]}">{page["title"]}</a></li>'
            )
        page_links = '\n'.join(page_links_html)
    else:
        page_links = '              <li>No pages available yet.</li>'
    
    # Listening data is optional: a fresh clone has never fetched, and the
    # build must still succeed. See specs/2026-08-09-spotify-listening-design.md
    listening_path = os.path.join(content_path, "listening.json")
    listening_data, listening_warning = load_listening(listening_path)
    if listening_warning:
        print(listening_warning)
    listening_tracks, listening_stamp = render_listening(listening_data)

    # Read template
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # Get current year
    current_year = datetime.datetime.now(datetime.UTC).year
    
    # Generate canonical URL
    base_url = "/"
    canonical = base_url
    
    # Replace placeholders
    landing_html = (
        template
        .replace("{{ Title }}", config["title"])
        .replace("{{ Description }}", config["description"])
        .replace("{{ Canonical }}", canonical)
        .replace("{{ SiteTitle }}", config["site_title"])
        .replace("{{ SiteDescription }}", config["site_description"])
        .replace("{{ SiteAuthor }}", config["site_author"])
        .replace("{{ Year }}", str(current_year))
        .replace("{{ PageLinks }}", page_links)
        .replace("{{ ListeningTracks }}", listening_tracks)
        .replace("{{ ListeningStamp }}", listening_stamp)
    )
    
    # Write output
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, 'w', encoding='utf-8') as f:
        f.write(landing_html)
    
    print(f"Landing page written to {dest_path}")
    print(f"Found {len(md_files)} page(s): {[p['title'] for p in md_files]}")
