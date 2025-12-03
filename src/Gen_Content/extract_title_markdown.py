def _unwrap_surrounding_fence(markdown: str) -> str:
    """If the whole document is wrapped in a fenced block (``` or ````), remove the outer fences.

    This handles cases where the author accidentally pasted a whole markdown file inside a
    code-fence (e.g. ````markdown ... ````). We only unwrap if the fence appears as the
    first non-empty line and there's a matching closing fence at the end of the file.
    """
    lines = markdown.splitlines()
    # Find first non-empty
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines):
        return markdown

    first = lines[i].lstrip()
    if not first.startswith('```'):
        return markdown

    # fence marker (like ``` or ````) - capture the exact fence string
    fence = first[: first.find(' ')].strip() if ' ' in first else first
    if not fence.startswith('```'):
        fence = first.split()[0]

    # find closing fence starting from the bottom
    j = len(lines) - 1
    while j >= 0 and lines[j].strip() == "":
        j -= 1
    if j <= i:
        return markdown

    last = lines[j].lstrip()
    if last.startswith(fence):
        # unwrap
        inner = lines[i + 1 : j]
        return "\n".join(inner).strip('\n')

    return markdown


def extract_title(markdown):
    # If the whole file is wrapped in a code-fence (e.g. ```markdown ... ```), unwrap it.
    markdown = _unwrap_surrounding_fence(markdown)

    lines = markdown.splitlines()
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()

    raise ValueError("No title found in markdown")
        