import datetime
import os
import sys
import shutil
from pathlib import Path
from Gen_Content.generate_page import generate_page
from Gen_Content.generate_landing_page import generate_landing_page
from Gen_Content.generate_blog_index import generate_blog_index

def copy_static_to_docs():
    """
    Copies all contents from static directory to docs directory.
    Deletes existing contents of docs directory first.
    Logs all operations to log.txt in the workspace root.
    Also renders all .md files in content/ to docs/*.html and sets index.html.
    """
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_path = os.path.join(workspace_root, "static")
    content_path = os.path.join(workspace_root, "content")
    template_path = os.path.join(workspace_root, "template.html")
    docs_path = os.path.join(workspace_root, "docs")
    log_path = os.path.join(workspace_root, "log.txt")
    
    with open(log_path, "w") as log_file:
        log_file.write(f"Build Operation - {datetime.datetime.now()}\n")
        log_file.write("=" * 50 + "\n\n")
    
    def log_message(message):
        with open(log_path, "a") as log_file:
            log_file.write(f"{datetime.datetime.now().strftime('%H:%M:%S')} - {message}\n")
        print(message)
    
    try:
        if not os.path.exists(static_path):
            log_message(f"ERROR: Static directory does not exist at {static_path}")
            return False
        if not os.path.exists(content_path):
            log_message(f"ERROR: Content directory does not exist at {content_path}")
            return False
        if not os.path.exists(template_path):
            log_message(f"ERROR: Template not found at {template_path}")
            return False
        
        log_message(f"Starting build from {static_path} to {docs_path}")
        
        # Delete and recreate docs directory
        if os.path.exists(docs_path):
            log_message("Deleting existing docs directory...")
            shutil.rmtree(docs_path)
        os.makedirs(docs_path)
        log_message("Created fresh docs directory")
        
        # Copy static files
        def copy_recursive(src_dir, dest_dir, relative_path=""):
            for item in os.listdir(src_dir):
                src_item = os.path.join(src_dir, item)
                dest_item = os.path.join(dest_dir, item)
                relative_item = os.path.join(relative_path, item) if relative_path else item
                if os.path.isdir(src_item):
                    os.makedirs(dest_item, exist_ok=True)
                    log_message(f"Created directory: {relative_item}")
                    copy_recursive(src_item, dest_item, relative_item)
                else:
                    shutil.copy2(src_item, dest_item)
                    file_size = os.path.getsize(src_item)
                    log_message(f"Copied file: {relative_item} ({file_size} bytes)")
        
        copy_recursive(static_path, docs_path)
        
        # Render all markdown files in content/ -> docs/*.html
        md_files = [f for f in os.listdir(content_path) if f.lower().endswith(".md")]
        if not md_files:
            log_message("WARNING: No markdown files found in content/")
        had_errors = False
        for md_name in sorted(md_files):
            src_md = os.path.join(content_path, md_name)
            out_html = os.path.join(docs_path, f"{os.path.splitext(md_name)[0]}.html")
            log_message(f"Generating page: {md_name} -> {os.path.basename(out_html)}")
            try:
                generate_page(src_md, template_path, out_html)
            except Exception as e:
                had_errors = True
                log_message(f"ERROR building {md_name}: {e}")
                import traceback
                log_message(traceback.format_exc())
                continue
        
        # Generate blog posts from content/dev_diary/
        blog_dir = os.path.join(content_path, "dev_diary")
        blog_posts_out = os.path.join(docs_path, "dev_diary")
        if os.path.exists(blog_dir):
            log_message("Generating blog posts from content/dev_diary/...")
            os.makedirs(blog_posts_out, exist_ok=True)
            blog_md_files = [f for f in os.listdir(blog_dir) if f.lower().endswith(".md")]
            for md_name in sorted(blog_md_files):
                src_md = os.path.join(blog_dir, md_name)
                out_html = os.path.join(blog_posts_out, f"{os.path.splitext(md_name)[0]}.html")
                log_message(f"  Generating blog post: {md_name}")
                try:
                    generate_page(src_md, template_path, out_html)
                except Exception as e:
                    had_errors = True
                    log_message(f"  ERROR building blog post {md_name}: {e}")
                    import traceback
                    log_message(traceback.format_exc())
                    continue
            
            # Generate blog index page
            dev_diary_template = os.path.join(workspace_root, "dev_diary_template.html")
            dev_diary_index = os.path.join(docs_path, "dev_diary.html")
            if os.path.exists(dev_diary_template):
                log_message("Generating blog index page...")
                try:
                    generate_blog_index(content_path, dev_diary_template, dev_diary_index)
                except Exception as e:
                    had_errors = True
                    log_message(f"ERROR generating blog index: {e}")
                    import traceback
                    log_message(traceback.format_exc())
            else:
                log_message(f"WARNING: dev_diary_template.html not found")
        else:
            log_message("No dev_diary subdirectory found, skipping blog generation")
        
        # Generate landing page as index.html
        titlepage_template = os.path.join(workspace_root, "titlepage.html")
        index_html = os.path.join(docs_path, "index.html")
        
        if os.path.exists(titlepage_template):
            log_message("Generating landing page...")
            try:
                site_config = {
                    "title": "Home - Portfolio",
                    "site_title": "Bret Zanotelli",
                    "site_description": "Developer | Hobbyist | Creator",
                    "site_author": "Bret Zanotelli",
                    "description": "Personal portfolio featuring development projects, resume, and creative pursuits"
                }
                generate_landing_page(content_path, titlepage_template, index_html, site_config)
                log_message("Landing page generated successfully as index.html")
            except Exception as e:
                had_errors = True
                log_message(f"ERROR generating landing page: {e}")
                import traceback
                log_message(traceback.format_exc())
        else:
            log_message(f"WARNING: titlepage.html template not found at {titlepage_template}")
            # Fallback to old behavior
            resume_html = os.path.join(docs_path, "resume.html")
            if os.path.exists(resume_html):
                shutil.copy2(resume_html, index_html)
                log_message("Set homepage: index.html copied from resume.html (fallback)")
            else:
                generated = [os.path.join(docs_path, f"{os.path.splitext(m)[0]}.html") for m in md_files]
                generated = [p for p in generated if os.path.exists(p)]
                if generated:
                    shutil.copy2(generated[0], index_html)
                    log_message(f"Set homepage: index.html copied from {os.path.basename(generated[0])} (fallback)")
                else:
                    log_message("WARNING: No pages generated to set as index.html")
        
        if had_errors:
            log_message("Build completed with errors (see above).")
            return False
        log_message("Build completed successfully!")
        return True
        
    except Exception as e:
        log_message(f"ERROR: {str(e)}")
        import traceback
        log_message(traceback.format_exc())
        return False

def main():
    """Main build function"""
    success = copy_static_to_docs()
    if success:
        print("\n✓ Site built successfully!")
        print("✓ Open docs/index.html to preview")
    else:
        print("\n✗ Build failed. Check log.txt for details.")
        sys.exit(1)

if __name__ == "__main__":
    main()
