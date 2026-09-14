from extract_markdown import extract_markdown_images, extract_markdown_links
from textnode import TextNode, TextType


def split_nodes_image(old_nodes):
    new_nodes = []

    for node in old_nodes:
        if node.text_type is not TextType.PLAIN_TEXT:
            new_nodes.append(node)
            continue

        parts = extract_markdown_images(node.text)

        if not parts:
            new_nodes.append(node)
            continue

        last_end = 0
        for alt_text, url in parts:
            start = node.text.find(f"![{alt_text}]({url})", last_end)
            if start > last_end:
                new_nodes.append(TextNode(node.text[last_end:start], TextType.PLAIN_TEXT))
            new_nodes.append(TextNode(alt_text, TextType.IMAGES, url))
            last_end = start + len(f"![{alt_text}]({url})")

        if last_end < len(node.text):
            new_nodes.append(TextNode(node.text[last_end:], TextType.PLAIN_TEXT))

    return new_nodes


def split_nodes_link(old_nodes):
    new_nodes = []

    for node in old_nodes:
        if node.text_type is not TextType.PLAIN_TEXT:
            new_nodes.append(node)
            continue

        parts = extract_markdown_links(node.text)

        if not parts:
            new_nodes.append(node)
            continue

        last_end = 0
        for link_text, url in parts:
            start = node.text.find(f"[{link_text}]({url})", last_end)
            if start > last_end:
                new_nodes.append(TextNode(node.text[last_end:start], TextType.PLAIN_TEXT))
            new_nodes.append(TextNode(link_text, TextType.LINKS, url))
            last_end = start + len(f"[{link_text}]({url})")

        if last_end < len(node.text):
            new_nodes.append(TextNode(node.text[last_end:], TextType.PLAIN_TEXT))

    return new_nodes