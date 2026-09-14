import re

from textnode import TextNode, TextType


def split_nodes_delimiter(old_nodes, delimiter, text_type):
    new_nodes = []

    for node in old_nodes:
        if node.text_type is not TextType.PLAIN_TEXT:
            new_nodes.append(node)
            continue

        # Single-char delimiters (_ and *) need a boundary check so they
        # don't split snake_case or file_names.
        if delimiter in ["_", "*"] and len(delimiter) == 1:
            pattern = rf'(?<!\w){re.escape(delimiter)}([^{re.escape(delimiter)}]+?){re.escape(delimiter)}(?!\w)'

            last_end = 0
            text = node.text
            has_matches = False

            for match in re.finditer(pattern, text):
                has_matches = True
                if match.start() > last_end:
                    new_nodes.append(TextNode(text[last_end:match.start()], TextType.PLAIN_TEXT))

                new_nodes.append(TextNode(match.group(1), text_type))
                last_end = match.end()

            if has_matches:
                if last_end < len(text):
                    new_nodes.append(TextNode(text[last_end:], TextType.PLAIN_TEXT))
            else:
                new_nodes.append(node)
        else:
            # Multi-character delimiters (** or __) split cleanly, no regex needed
            parts = node.text.split(delimiter)

            if len(parts) % 2 == 0:
                raise ValueError(f"unbalanced delimiters: {delimiter}")
                
            for i, part in enumerate(parts):
                if part == "":
                    continue
                if i % 2 == 0:
                    new_nodes.append(TextNode(part, TextType.PLAIN_TEXT))
                else:
                    new_nodes.append(TextNode(part, text_type))

                
    return new_nodes
