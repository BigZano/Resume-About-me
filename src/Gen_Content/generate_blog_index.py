import os
import re
from math import ceil
from pathlib import Path
from datetime import datetime

def _extract_page_date(markdown: str) -> tuple[str, bool]:
    """Extract page date from HTML comment or filename"""
    pattern = r'<!--\s*page-date:\s*(\d{4}-\d{2}-\d{2})\s*-->'
    match = re.search(pattern, markdown)
    if match:
        return match.group(1), True
    return datetime.now().strftime('%Y-%m-%d'), False

def _inject_page_date(markdown: str, date_str: str) -> str:
    """Inject page-date comment at the top of the markdown file"""
    comment = f'<!-- page-date: {date_str} -->\n'
    lines = markdown.split('\n')
    insert_pos = 0
    
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

def _extract_excerpt(markdown: str, max_len: int = 200) -> str:
    """Extract first paragraph as excerpt"""
    # Strip HTML comments
    markdown = re.sub(r'<!--.*?-->', '', markdown, flags=re.DOTALL)
    
    for line in markdown.splitlines():
        s = line.strip()
        if not s:
            continue
        # Skip headings, images, lists, blockquotes, links, HTML tags
        if s.startswith(("#", "!", "-", "*", ">", "[", "<")):
            continue
        s = re.sub(r"\s+", " ", s)
        return (s[:max_len] + "…") if len(s) > max_len else s
    return "Read more..."

def _extract_title_from_filename(filename: str) -> str:
    """Extract title from blog post filename: YYYY-MM-DD-title-here.md"""
    # Remove .md extension
    name = filename.replace('.md', '')
    # Split by date pattern
    parts = name.split('-', 3)
    if len(parts) >= 4:
        # parts[0] = year, parts[1] = month, parts[2] = day, parts[3] = title
        title = parts[3].replace('-', ' ').title()
        return title
    return name.replace('-', ' ').title()

# ARCHIVED: Social media share links removed - see .archive/social_media_integration/
# def _build_share_comment(post_url: str, title: str, site_base_url: str) -> str:
#     """Return commented-out share links for future activation"""
#     ...

def _build_pagination_nav(current_page: int, total_pages: int, base_name: str, suffix: str) -> str:
    """Generate pagination navigation HTML"""
    if total_pages <= 1:
        return ""

    def page_href(page: int) -> str:
        return f"{base_name}{suffix}" if page == 1 else f"{base_name}-page-{page}{suffix}"

    nav_parts: list[str] = ["<nav class=\"blog-pagination\" aria-label=\"Blog pages\">"]

    if current_page > 1:
        prev_href = page_href(current_page - 1)
        nav_parts.append(f"  <a class=\"nav-link\" href=\"{prev_href}\">← Newer posts</a>")
    else:
        nav_parts.append("  <span class=\"nav-link disabled\">← Newer posts</span>")

    page_links = []
    for page in range(1, total_pages + 1):
        if page == current_page:
            page_links.append(f"  <span class=\"page-link current\">{page}</span>")
        else:
            page_links.append(f"  <a class=\"page-link\" href=\"{page_href(page)}\">{page}</a>")
    nav_parts.extend(page_links)

    if current_page < total_pages:
        next_href = page_href(current_page + 1)
        nav_parts.append(f"  <a class=\"nav-link\" href=\"{next_href}\">Older posts →</a>")
    else:
        nav_parts.append("  <span class=\"nav-link disabled\">Older posts →</span>")

    nav_parts.append("</nav>")
    return "\n".join(nav_parts) + "\n"


def generate_blog_index(content_dir: str, template_path: str, dest_path: str, subdocs_dir: str = "dev_diary", posts_per_page: int = 5, site_base_url: str | None = None):
    """
    Generate a blog index page listing all posts in content/dev_diary/
    
    Args:
        content_dir: Path to content directory (e.g., /path/to/content)
        template_path: Path to dev_diary_template.html
        dest_path: Output path for dev_diary.html
        subdocs_dir: Subdirectory name containing blog posts (default: dev_diary)
    """
    print(f"Generating blog index from {content_dir}/{subdocs_dir}")
    
    blog_dir = Path(content_dir) / subdocs_dir
    if not blog_dir.exists():
        print(f"  ⚠ Blog directory not found: {blog_dir}")
        return
    
    # Get all .md files in dev_diary/
    posts = []
    for md_file in sorted(blog_dir.glob("*.md"), reverse=True):
        with open(md_file, 'r', encoding='utf-8') as f:
            markdown = f.read()
        
        # Extract or inject date
        page_date, date_found = _extract_page_date(markdown)
        if not date_found:
            # Try to extract from filename (YYYY-MM-DD-title.md)
            filename_date_match = re.match(r'(\d{4}-\d{2}-\d{2})', md_file.name)
            if filename_date_match:
                page_date = filename_date_match.group(1)
            
            # Inject the date into the file
            markdown = _inject_page_date(markdown, page_date)
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(markdown)
            print(f"  → Added page-date: {page_date} to {md_file.name}")
        
        # Extract title from file content
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from extract_title_markdown import extract_title
        
        markdown_clean = re.sub(r'<!--.*?-->', '', markdown, flags=re.DOTALL)
        try:
            title = extract_title(markdown_clean)
        except ValueError:
            # Fallback to filename-based title
            title = _extract_title_from_filename(md_file.name)
        
        excerpt = _extract_excerpt(markdown_clean)
        
        # Generate HTML filename
        html_filename = md_file.stem + ".html"
        
        posts.append({
            'title': title,
            'date': page_date,
            'excerpt': excerpt,
            'url': f"{subdocs_dir}/{html_filename}",
            'filename': md_file.name
        })
    
    posts_per_page = max(1, posts_per_page)
    total_posts = len(posts)
    total_pages = max(1, ceil(total_posts / posts_per_page))

    base_path = Path(dest_path)
    base_name = base_path.stem
    suffix = base_path.suffix

    site_base_url = (site_base_url or os.environ.get("SITE_BASE_URL", "")).rstrip('/')

    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    for page_num in range(1, total_pages + 1):
        start_idx = (page_num - 1) * posts_per_page
        page_posts = posts[start_idx:start_idx + posts_per_page]

        posts_html = '<section class="blog-posts">\n'
        for post in page_posts:
            # Social media share links removed - see .archive/social_media_integration/
            posts_html += f'''
        <article class="blog-post-preview">
            <header>
                <h2><a href="{post['url']}">{post['title']}</a></h2>
                <time datetime="{post['date']}">{post['date']}</time>
            </header>
            <p class="excerpt">{post['excerpt']}</p>
            <a href="{post['url']}" class="read-more">Read more →</a>
        </article>
'''
        posts_html += '</section>\n'

        pagination_nav = _build_pagination_nav(page_num, total_pages, base_name, suffix)
        page_html = template.replace("{{ BlogPosts }}", posts_html)
        if "{{ PaginationNav }}" in page_html:
            page_html = page_html.replace("{{ PaginationNav }}", pagination_nav)
        else:
            page_html = page_html.replace(posts_html, posts_html + pagination_nav)

        page_dest = base_path if page_num == 1 else base_path.with_name(f"{base_name}-page-{page_num}{suffix}")
        os.makedirs(page_dest.parent, exist_ok=True)
        with open(page_dest, 'w', encoding='utf-8') as f:
            f.write(page_html)

        print(f"Blog index written to {page_dest}")

    print(f"Found {len(posts)} post(s) across {total_pages} page(s): {[p['title'] for p in posts]}")
