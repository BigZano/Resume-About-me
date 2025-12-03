def markdown_to_blocks(markdown_text):
    """
    converts markdown to a list of blocks
    like headers, paragraphs, etc. 
    """
    blocks = []
    current_paragraph = []
    in_code_fence = False

    lines = markdown_text.split('\n')
    for line in lines:
        line = line.rstrip()
        
        # Check for code fence markers
        if line.strip().startswith('```'):
            if not in_code_fence:
                # Starting a code fence
                if current_paragraph:
                    block = "\n".join(current_paragraph).strip()
                    blocks.append(block)
                    current_paragraph = []
                in_code_fence = True
                current_paragraph.append(line.strip())
            else:
                # Ending a code fence
                current_paragraph.append(line.strip())
                block = "\n".join(current_paragraph).strip()
                blocks.append(block)
                current_paragraph = []
                in_code_fence = False
            continue

        if in_code_fence:
            # Inside code fence, preserve everything including blank lines
            current_paragraph.append(line.strip())
            continue

        if line == "":
            if current_paragraph:
                block = "\n".join(current_paragraph).strip()
                blocks.append(block)
                current_paragraph = []
        else:
            stripped = line.strip()
            # Headings should always be their own block
            if stripped.startswith('#') and ' ' in stripped:
                # Flush current paragraph first
                if current_paragraph:
                    block = "\n".join(current_paragraph).strip()
                    blocks.append(block)
                    current_paragraph = []
                # Add the heading as its own block
                blocks.append(stripped)
            else:
                current_paragraph.append(stripped)
    
    # Handle the final block if it doesn't end with a blank line
    if current_paragraph:
        block = "\n".join(current_paragraph).strip()
        blocks.append(block)
    
    return blocks