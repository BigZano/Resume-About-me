def _unwrap_surrounding_fence(markdown: str) -> str:
    """Strip outer ``` fences if the whole file was accidentally pasted inside one.

    Only unwraps if the fence is the first non-empty line and a matching
    closing fence ends the file.
    """
    lines = markdown.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines):
        return markdown

    first = lines[i].lstrip()
    if not first.startswith('```'):
        return markdown

    fence = first[: first.find(' ')].strip() if ' ' in first else first
    if not fence.startswith('```'):
        fence = first.split()[0]

    j = len(lines) - 1
    while j >= 0 and lines[j].strip() == "":
        j -= 1
    if j <= i:
        return markdown

    last = lines[j].lstrip()
    if last.startswith(fence):
        inner = lines[i + 1 : j]
        return "\n".join(inner).strip('\n')

    return markdown


def extract_title(markdown):
    markdown = _unwrap_surrounding_fence(markdown)

    lines = markdown.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()

    raise ValueError("No title found in markdown")
        