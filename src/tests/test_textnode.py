import unittest

from src.textnode import TextNode, TextType


class TestTextNode(unittest.TestCase):
    def test_eq(self):
        node = TextNode("This is a text node", TextType.BOLD_TEXT)
        node2 = TextNode("This is a text node", TextType.BOLD_TEXT)
        self.assertEqual(node, node2)

    def test_neq(self):
        node = TextNode("This is a text node", TextType.BOLD_TEXT)
        node2 = TextNode("This is an italic node", TextType.ITALIC_TEXT)
        self.assertNotEqual(node, node2)

    def test_url(self):
        node = TextNode("This is a link", TextType.LINKS, url="https://google.com")
        node2 = TextNode("This is a link", TextType.LINKS, url="https://google.com")
        self.assertEqual(node, node2)

    def test_neq_url(self):
        node = TextNode("This is a link", TextType.LINKS, url="https://google.com")
        node2 = TextNode("This is a link", TextType.LINKS, url="https://bing.com")
        self.assertNotEqual(node, node2)

    def test_repr(self):
        node = TextNode("This is a link", TextType.LINKS, url="https://google.com")
        self.assertEqual(repr(node), "TextNode(This is a link, link, https://google.com)")

    def test_repr_no_url(self):
        node = TextNode("This is a bold text", TextType.BOLD_TEXT)
        self.assertEqual(repr(node), "TextNode(This is a bold text, bold, None)")

    


if __name__ == "__main__":
    unittest.main()