import re


def extract_markdown_images(text):
    # takes markdown text and returns a list of tuples
    pattern = r"!\[([^\[\]]*)\]\(([^\(\)]*)\)"
    matches = re.findall(pattern, text)
    return [(alt_text, url) for alt_text, url in matches]

def extract_markdown_links(text):
    # Same as above but for links
    pattern = r"(?<!!)\[([^\[\]]*)\]\(([^\(\)]*)\)"
    matches = re.findall(pattern, text)
    return [(link_text, url) for link_text, url in matches]
