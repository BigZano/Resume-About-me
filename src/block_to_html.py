import re
from markdown_to_blocks import markdown_to_blocks
from htmlnode import HTMLNode, LeafNode, ParentNode, text_node_to_html_node
from textnode import TextNode, TextType
from text_to_textnodes import text_to_textnodes

def text_to_children(text):
    nodes = text_to_textnodes(text)
    children = []
    for tn in nodes:
        html_node = text_node_to_html_node(tn)
        if html_node is None:
            raise ValueError(f"Unexpected None from text_node_to_html_node for {tn}")
        children.append(html_node)
    return children

def _indent_width(whitespace):
    """Normalize tabs to 4 spaces"""
    return len(whitespace.replace("\t", "    "))


def _is_list_block(block, ordered=False):
    """
    Check if block is a list, allowing continuation lines.
    A valid list block:
    - Starts with at least one list marker (- or N.)
    - Can have continuation lines (indented or empty lines)
    """
    if ordered:
        marker_pattern = re.compile(r"^\s*\d+\.\s+")
    else:
        marker_pattern = re.compile(r"^\s*-\s+")

    lines = block.splitlines()
    if not lines:
        return False

    # Must have at least one line matching list marker
    has_list_marker = any(marker_pattern.match(l) for l in lines)
    if not has_list_marker:
        return False

    # All non-empty lines must either:
    # - Match list marker (start of item)
    # - Be indented (continuation of previous item)
    for line in lines:
        if not line.strip():  # empty line OK
            continue
        if marker_pattern.match(line):  # list marker OK
            continue
        if line[0] in (' ', '\t'):  # indented (continuation) OK
            continue
        # Non-indented line without marker = not a list
        return False

    return True


def _parse_list_items(block, ordered=False):
    """Parse list items (ordered or unordered) with support for nesting via indentation and continuation lines"""
    if ordered:
        pattern = re.compile(r"^(\s*)\d+\.\s+(.*)$")
        list_tag = "ol"
    else:
        pattern = re.compile(r"^(\s*)-\s+(.*)$")
        list_tag = "ul"

    # Tree structure: [{"text": "...", "children": [ ... ]}, ...]
    root = []
    stack = [(-1, root)]  # (indent_level, children_list)
    current_node = None  # Track last node for appending continuation lines

    for raw_line in block.splitlines():
        if not raw_line.strip():
            continue

        m = pattern.match(raw_line)
        if m:
            # This is a list marker line
            indent = _indent_width(m.group(1))
            item_text = m.group(2).strip()

            # Pop stack until we find the correct parent indent level
            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()

            current_node = {"text": item_text, "children": []}
            stack[-1][1].append(current_node)
            stack.append((indent, current_node["children"]))
        elif current_node and raw_line[0] in (' ', '\t'):
            # This is a continuation line (indented, no marker)
            # Append to current node's text with a space
            continuation = raw_line.strip()
            if continuation:
                current_node["text"] += " " + continuation

    def to_list_node(nodes):
        """Recursively convert tree structure to HTML nodes"""
        list_children = []
        for n in nodes:
            li_children = text_to_children(n["text"])
            if n["children"]:
                li_children.append(to_list_node(n["children"]))
            list_children.append(ParentNode("li", li_children))
        return ParentNode(list_tag, list_children)

    return to_list_node(root)


def markdown_to_html_node(markdown):
    blocks = markdown_to_blocks(markdown)
    children = []
    for block in blocks:
        text = block.strip()
        if text.startswith("```") and text.endswith("```"):
            code_text = "\n".join(block.splitlines()[1:-1]) + "\n"
            children.append(ParentNode("pre", [ParentNode("code", [LeafNode(None, code_text)])]))
            continue
        elif text.startswith("###### "):
            children.append(ParentNode("h6", text_to_children(block[7:].strip())))
        elif text.startswith("##### "):
            children.append(ParentNode("h5", text_to_children(block[6:].strip())))
        elif text.startswith("#### "):
            children.append(ParentNode("h4", text_to_children(block[5:].strip())))
        elif text.startswith("### "):
            children.append(ParentNode("h3", text_to_children(block[4:].strip())))
        elif text.startswith("## "):
            children.append(ParentNode("h2", text_to_children(block[3:].strip())))
        elif text.startswith("# "):
            children.append(ParentNode("h1", text_to_children(block[2:].strip())))
        elif text.startswith("> "):
            quote_lines = []
            for l in block.splitlines():
                if l == ">":
                    continue
                if l.startswith("> "):
                    quote_lines.append(l[2:])
                else:
                    break
            cleaned = "\n".join(quote_lines).strip()
            if not cleaned:
                continue  # skip empty blockquote
            children.append(ParentNode("blockquote", text_to_children(cleaned)))
        elif _is_list_block(block, ordered=True):
            # Ordered list (handles indentation and continuation lines)
            children.append(_parse_list_items(block, ordered=True))
        elif _is_list_block(block, ordered=False):
            # Unordered list (handles indentation and continuation lines)
            children.append(_parse_list_items(block, ordered=False))
        else:
            lines = [l.strip() for l in block.splitlines()]
            para_text = " ".join([l for l in lines if l])
            inlines = text_to_children(para_text)
            children.append(ParentNode("p", inlines))
    return ParentNode("div", children)
