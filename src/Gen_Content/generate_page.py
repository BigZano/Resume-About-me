import os
import re
from datetime import UTC, datetime
from pathlib import Path


def _strip_html_comments(markdown: str) -> str:
    """Remove HTML comments from markdown"""
    return re.sub(r'<!--.*?-->', '', markdown, flags=re.DOTALL)

def _first_paragraph(markdown: str, max_len: int = 180) -> str:
    """Extract first non-heading paragraph for meta description"""
    markdown = _strip_html_comments(markdown)
    for line in markdown.splitlines():
        s = line.strip()
        if not s:
            continue
        # REFACTOR: name this tuple (e.g. _NON_PROSE_PREFIXES) instead of
        # a bare literal — headings/images/lists/quotes/links/HTML tags.
        if s.startswith(("#", "!", "-", "*", ">", "[", "<")):
            continue
        s = re.sub(r"\s+", " ", s)
        return (s[:max_len] + "…") if len(s) > max_len else s
    return "Professional resume and portfolio"

def _to_canonical(base_url: str, dest_path: str) -> str:
    """Generate canonical URL from destination path"""
    p = Path(dest_path)
    try:
        rel = p.relative_to(Path(dest_path).parent.parent / "docs")
    except ValueError:
        # dest_path isn't under docs/ -- fall back to just the filename
        rel = Path(p.name)
    
    url_path = "/" if rel.as_posix() in ("", ".") else "/" + rel.as_posix()
    if url_path.endswith("/index.html"):
        url_path = url_path[: -len("index.html")]
    if not base_url.endswith("/"):
        base_url += "/"
    return (base_url.rstrip("/") + url_path).replace("//", "/")

def _extract_page_date(markdown: str) -> tuple[str, bool]:
    """Extract page date from <!-- page-date: YYYY-MM-DD --> or default to today."""
    pattern = r'<!--\s*page-date:\s*(\d{4}-\d{2}-\d{2})\s*-->'
    match = re.search(pattern, markdown)
    if match:
        return match.group(1), True
    else:
        return datetime.now(UTC).strftime('%Y-%m-%d'), False

def _inject_page_date(markdown: str, date_str: str) -> str:
    """Insert a page-date comment after any leading HTML comments, else at the top."""
    comment = f'<!-- page-date: {date_str} -->\n'
    lines = markdown.split('\n')
    insert_pos = 0
    
    # REFACTOR: extract as a named _find_insertion_point(lines) helper
    # instead of inline step-labels.
    for i, line in enumerate(lines):
        if line.strip().startswith('<!--'):
            if '-->' in line:
                insert_pos = i + 1
            else:
                for j in range(i + 1, len(lines)):
                    if '-->' in lines[j]:
                        insert_pos = j + 1
                        break
        elif line.strip() and not line.strip().startswith('#'):
            break
    
    lines.insert(insert_pos, comment.rstrip())
    return '\n'.join(lines)

def _render_markdown(markdown: str, page_date: str | None = None, is_blog_post: bool = False) -> str:
    """Convert markdown to HTML using existing pipeline"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from block_to_html import markdown_to_html_node

    html = markdown_to_html_node(markdown).to_html()

    if is_blog_post and page_date:
        # Parse ISO date to readable format
        try:
            date_obj = datetime.strptime(page_date, '%Y-%m-%d').replace(tzinfo=UTC)
            readable_date = date_obj.strftime('%B %d, %Y')
            html = html.replace('</h1>', f'</h1><p class="post-date">{readable_date}</p>', 1)
        except ValueError as exc:
            # page_date didn't match YYYY-MM-DD -- skip the date stamp
            # rather than fail the whole page build over it.
            print(f"  Warning: could not parse page_date {page_date!r}: {exc}")

    return html

def generate_page(from_path, template_path, dest_path, is_blog_post=False):
    """Generate a single HTML page from markdown"""
    print(f"Generating page from {from_path} to {dest_path}")
    
    with open(from_path, "r", encoding="utf-8") as f:
        markdown = f.read()

    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from Gen_Content.extract_title_markdown import extract_title
    
    # REFACTOR: fragile ordering — date extraction depends on running
    # before HTML comments are stripped. Fold both into one step.
    page_date, date_found = _extract_page_date(markdown)

    if not date_found:
        markdown = _inject_page_date(markdown, page_date)
        with open(from_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"  → Added page-date: {page_date}")

    markdown_clean = _strip_html_comments(markdown)
    
    title = extract_title(markdown_clean)
    description = _first_paragraph(markdown_clean)
    base_url = "/"
    canonical = _to_canonical(base_url, dest_path)

    content_html = _render_markdown(markdown_clean, page_date, is_blog_post)

    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # REFACTOR: extract this prefix computation and the rewrite below
    # into one _rewrite_asset_paths(html, dest_path) helper.
    dest_path_obj = Path(dest_path)
    try:
        docs_dir = dest_path_obj.parent
        while docs_dir.name and docs_dir.name != 'docs':
            docs_dir = docs_dir.parent

        rel_path = dest_path_obj.relative_to(docs_dir)
        depth = len(rel_path.parts) - 1
        path_prefix = '../' * depth if depth > 0 else './'
    except ValueError:
        # dest_path isn't under a 'docs' directory -- fall back to current dir
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
    
    if path_prefix != './':
        page_html = page_html.replace('href="./', f'href="{path_prefix}')
        page_html = page_html.replace('src="./', f'src="{path_prefix}')

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(page_html)
    
    print(f"Page written to {dest_path}")