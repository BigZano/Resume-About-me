def markdown_to_blocks(markdown_text):
    """
    converts markdown to a list of blocks
    like headers, paragraphs, etc.
    """
    blocks = []
    current_paragraph = []
    in_code_fence = False

    lines = markdown_text.split("\n")
    for raw_line in lines:
        line = raw_line.rstrip()

        # Check for code fence markers (allow optional indent before ```)
        if line.lstrip().startswith("```"):
            if not in_code_fence:
                if current_paragraph:
                    block = "\n".join(current_paragraph).strip("\n")
                    blocks.append(block)
                    current_paragraph = []
                in_code_fence = True
                current_paragraph.append(line.lstrip())
            else:
                current_paragraph.append(line.lstrip())
                block = "\n".join(current_paragraph).strip("\n")
                blocks.append(block)
                current_paragraph = []
                in_code_fence = False
            continue

        if in_code_fence:
            # Preserve inside code fences
            current_paragraph.append(line)
            continue

        if line.strip() == "":
            if current_paragraph:
                block = "\n".join(current_paragraph).strip("\n")
                blocks.append(block)
                current_paragraph = []
        else:
            stripped = line.strip()

            # Keep heading behavior for top-level headings
            if line == line.lstrip() and stripped.startswith("#") and " " in stripped:
                if current_paragraph:
                    block = "\n".join(current_paragraph).strip("\n")
                    blocks.append(block)
                    current_paragraph = []
                blocks.append(stripped)
            else:
                # Preserve leading spaces for nested list parsing
                current_paragraph.append(line)

    if current_paragraph:
        block = "\n".join(current_paragraph).strip("\n")
        blocks.append(block)

    return blocks