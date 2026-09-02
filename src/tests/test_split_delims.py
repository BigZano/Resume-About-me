import unittest

from src.split_nodes import split_nodes_delimiter
from src.textnode import TextNode, TextType


class TestSplitFunctions(unittest.TestCase):
    def test_split_code_simple(self):
        nodes = [TextNode("A `B` C", TextType.PLAIN_TEXT)]
        out = split_nodes_delimiter(nodes, "`", TextType.CODE_TEXT)
        self.assertEqual(
            [(n.text, n.text_type) for n in out],
            [("A ", TextType.PLAIN_TEXT), ("B", TextType.CODE_TEXT), (" C", TextType.PLAIN_TEXT)]
        )

    def test_split_bold_simple(self):
        nodes = [TextNode("Hi **there** friend", TextType.PLAIN_TEXT)]
        out = split_nodes_delimiter(nodes, "**", TextType.BOLD_TEXT)
        self.assertEqual(
            [(n.text, n.text_type) for n in out],
            [("Hi ", TextType.PLAIN_TEXT), ("there", TextType.BOLD_TEXT), (" friend", TextType.PLAIN_TEXT)],
        )

    def test_non_plain_passthrough(self):
        nodes = [TextNode("x", TextType.BOLD_TEXT)]
        out = split_nodes_delimiter(nodes, "`", TextType.CODE_TEXT)
        self.assertEqual(out[0].text, "x")
        self.assertEqual(out[0].text_type, TextType.BOLD_TEXT)


    def test_unbalanced_raises(self):
        nodes = [TextNode("A `B C", TextType.PLAIN_TEXT)]
        with self.assertRaises(ValueError):
            split_nodes_delimiter(nodes, "`", TextType.CODE_TEXT)

    
    def test_skips_empty_parts(self):
        nodes = [TextNode("**bold**", TextType.PLAIN_TEXT)]
        out = split_nodes_delimiter(nodes, "**", TextType.BOLD_TEXT)
        self.assertEqual(
            [(n.text, n.text_type) for n in out],
            [("bold", TextType.BOLD_TEXT)],
        )


    def test_split_italic_simple(self):
        nodes = [TextNode("This is *italic* text", TextType.PLAIN_TEXT)]
        out = split_nodes_delimiter(nodes, "*", TextType.ITALIC_TEXT)
        self.assertEqual(
            [(n.text, n.text_type) for n in out],
            [("This is ", TextType.PLAIN_TEXT), ("italic", TextType.ITALIC_TEXT), (" text", TextType.PLAIN_TEXT)],
        )

    def test_split_multiple_delimiters(self):
        nodes = [TextNode("A `B` C `D` E", TextType.PLAIN_TEXT)]
        out = split_nodes_delimiter(nodes, "`", TextType.CODE_TEXT)
        self.assertEqual(
            [(n.text, n.text_type) for n in out],
            [("A ", TextType.PLAIN_TEXT), ("B", TextType.CODE_TEXT), (" C ", TextType.PLAIN_TEXT), ("D", TextType.CODE_TEXT), (" E", TextType.PLAIN_TEXT)],
        )