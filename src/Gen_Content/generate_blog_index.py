import os
import re
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

def generate_blog_index(content_dir: str, template_path: str, dest_path: str, subdocs_dir: str = "dev_diary"):
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
    
    # Generate HTML for post listing
    posts_html = '<section class="blog-posts">\n'
    for post in posts:
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
    
    # Load template and replace placeholder
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    page_html = template.replace("{{ BlogPosts }}", posts_html)
    
    # Write output
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, 'w', encoding='utf-8') as f:
        f.write(page_html)
    
    print(f"Blog index written to {dest_path}")
    print(f"Found {len(posts)} post(s): {[p['title'] for p in posts]}")
