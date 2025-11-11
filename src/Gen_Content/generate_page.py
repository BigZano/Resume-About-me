import os
import re
from pathlib import Path
from datetime import datetime

def _strip_html_comments(markdown: str) -> str:
    """Remove HTML comments from markdown"""
    return re.sub(r'<!--.*?-->', '', markdown, flags=re.DOTALL)

def _first_paragraph(markdown: str, max_len: int = 180) -> str:
    """Extract first non-heading paragraph for meta description"""
    # Strip HTML comments first
    markdown = _strip_html_comments(markdown)
    for line in markdown.splitlines():
        s = line.strip()
        if not s:
            continue
        # Skip headings, images, lists, blockquotes, links, and HTML tags
        if s.startswith(("#", "!", "-", "*", ">", "[", "<")):
            continue
        s = re.sub(r"\s+", " ", s)
        return (s[:max_len] + "…") if len(s) > max_len else s
    return "Professional resume and portfolio"

def _to_canonical(base_url: str, dest_path: str) -> str:
    """Generate canonical URL from destination path"""
    p = Path(dest_path)
    try:
        # Try to get relative path from docs directory
        rel = p.relative_to(Path(dest_path).parent.parent / "docs")
    except (ValueError, Exception):
        # Fallback: just use the filename
        rel = Path(p.name)
    
    url_path = "/" if rel.as_posix() in ("", ".") else "/" + rel.as_posix()
    if url_path.endswith("/index.html"):
        url_path = url_path[: -len("index.html")]
    if not base_url.endswith("/"):
        base_url += "/"
    return (base_url.rstrip("/") + url_path).replace("//", "/")

def _extract_page_date(markdown: str) -> tuple[str, bool]:
    """
    Extract page date from HTML comment: <!-- page-date: YYYY-MM-DD -->
    Returns (date_string, found_in_file)
    If not found, returns (today's date, False)
    """
    pattern = r'<!--\s*page-date:\s*(\d{4}-\d{2}-\d{2})\s*-->'
    match = re.search(pattern, markdown)
    if match:
        return match.group(1), True
    else:
        # Return today's date in YYYY-MM-DD format
        return datetime.now().strftime('%Y-%m-%d'), False

def _inject_page_date(markdown: str, date_str: str) -> str:
    """
    Inject page-date comment at the top of the markdown file (after any existing comments)
    """
    comment = f'<!-- page-date: {date_str} -->\n'
    
    # If file already starts with HTML comments, add after them
    # Otherwise, add at the very top
    lines = markdown.split('\n')
    insert_pos = 0
    
    for i, line in enumerate(lines):
        if line.strip().startswith('<!--'):
            # Find the end of this comment block
            if '-->' in line:
                insert_pos = i + 1
            else:
                # Multi-line comment, find closing
                for j in range(i + 1, len(lines)):
                    if '-->' in lines[j]:
                        insert_pos = j + 1
                        break
        elif line.strip() and not line.strip().startswith('#'):
            # Hit actual content, stop looking
            break
    
    lines.insert(insert_pos, comment.rstrip())
    return '\n'.join(lines)

def _render_markdown(markdown: str) -> str:
    """Convert markdown to HTML using existing pipeline"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from block_to_html import markdown_to_html_node
    
    return markdown_to_html_node(markdown).to_html()

def generate_page(from_path, template_path, dest_path):
    """Generate a single HTML page from markdown"""
    print(f"Generating page from {from_path} to {dest_path}")
    
    with open(from_path, "r", encoding="utf-8") as f:
        markdown = f.read()

    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from Gen_Content.extract_title_markdown import extract_title
    
    # Extract page date (before stripping comments)
    page_date, date_found = _extract_page_date(markdown)
    
    # If no date was found, inject it into the source file
    if not date_found:
        markdown = _inject_page_date(markdown, page_date)
        # Write back to source file to preserve the date
        with open(from_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"  → Added page-date: {page_date}")
    
    # Strip HTML comments before processing
    markdown_clean = _strip_html_comments(markdown)
    
    title = extract_title(markdown_clean)
    description = _first_paragraph(markdown_clean)
    base_url = "/"
    canonical = _to_canonical(base_url, dest_path)

    content_html = _render_markdown(markdown_clean)

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # Determine if page is in subdirectory and adjust CSS paths
    dest_path_obj = Path(dest_path)
    try:
        # Get relative path from docs directory
        docs_dir = dest_path_obj.parent
        while docs_dir.name and docs_dir.name != 'docs':
            docs_dir = docs_dir.parent
        
        rel_path = dest_path_obj.relative_to(docs_dir)
        # Count directory depth (excluding filename)
        depth = len(rel_path.parts) - 1
        
        # Create path prefix (../ for each level deep)
        path_prefix = '../' * depth if depth > 0 else './'
    except (ValueError, Exception):
        # Fallback to current directory
        path_prefix = './'
    
    page_html = (
        template
        .replace("{{ Title }}", title)
        .replace("{{ Content }}", content_html)
        .replace("{{ Description }}", description)
        .replace("{{ Canonical }}", canonical)
        .replace("{{ BaseUrl }}", base_url)
        .replace("{{ PageDate }}", page_date)
    )
    
    # Fix CSS/asset paths for subdirectories
    if path_prefix != './':
        page_html = page_html.replace('href="./', f'href="{path_prefix}')
        page_html = page_html.replace('src="./', f'src="{path_prefix}')

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(page_html)
    
    print(f"Page written to {dest_path}")