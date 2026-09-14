from split_images_and_links import *
from split_nodes import split_nodes_delimiter
from textnode import TextNode, TextType


def text_to_textnodes(text):
    nodes = [TextNode(text, TextType.PLAIN_TEXT)]
    # Code first, so content like Req_bot is protected from later delimiters.
    nodes = split_nodes_delimiter(nodes, "`", TextType.CODE_TEXT)
    # Images/links before delimiters, so underscores in URLs aren't split.
    nodes = split_nodes_image(nodes)
    nodes = split_nodes_link(nodes)
    nodes = split_nodes_delimiter(nodes, "**", TextType.BOLD_TEXT)
    nodes = split_nodes_delimiter(nodes, "__", TextType.BOLD_TEXT)
    nodes = split_nodes_delimiter(nodes, "*", TextType.ITALIC_TEXT)
    nodes = split_nodes_delimiter(nodes, "_", TextType.ITALIC_TEXT)
    return nodes
    



