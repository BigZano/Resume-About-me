import unittest

from src.htmlnode import HTMLNode, LeafNode, ParentNode, text_node_to_html_node
from src.textnode import TextNode, TextType


class TestHTMLNode(unittest.TestCase):
    def test_init(self):
        node = HTMLNode("div", "Hello", [HTMLNode("span", "World")], {"class": "my-class"})
        self.assertEqual(node.tag, "div")
        self.assertEqual(node.value, "Hello")
        self.assertEqual(len(node.children), 1)
        self.assertEqual(node.props, {"class": "my-class"})

    def test_props_to_html(self):
        node = HTMLNode("div", props={"class": "my-class", "id": "my-id"})
        props_html = node.props_to_html()
        self.assertIn('class="my-class"', props_html)
        self.assertIn('id="my-id"', props_html)
        self.assertTrue(props_html.startswith(" "))
        self.assertTrue(props_html.endswith(" "))

    def test_neq_props_to_html(self):
        node = HTMLNode("div")
        props_html = node.props_to_html()
        self.assertEqual(props_html, "")

    def test_repr(self):
        node = HTMLNode("div", "Hello", [HTMLNode("span", "World")], {"class": "my-class"})
        self.assertEqual(repr(node), "HTMLNode(tag=div, value=Hello, children=[HTMLNode(tag=span, value=World, children=[], props={})], props={'class': 'my-class'})")

    def test_leaf_node_to_html(self):
        leaf = LeafNode("p", "This is a paragraph", props={"class": "text"})
        html = leaf.to_html()
        self.assertEqual(html, '<p class="text">This is a paragraph</p>')
    
    def test_leaf_node_no_tag(self):
        leaf = LeafNode(None, "Just text")
        html = leaf.to_html()
        self.assertEqual(html, "Just text")

    def test_leaf_node_no_value(self):
        leaf = LeafNode("p", None)
        with self.assertRaises(ValueError):
            leaf.to_html()
    
    def test_parent_node_to_html(self):
        child1 = LeafNode("span", "Child 1")
        child2 = LeafNode("span", "Child 2", props={"class": "highlight"})
        parent = ParentNode("div", children=[child1, child2], props={"id": "container"})
        html = parent.to_html()
        self.assertEqual(html, '<div id="container"><span>Child 1</span><span class="highlight">Child 2</span></div>')

    def test_text_node_to_html_node_bold(self):
        text_node = TextNode("Bold Text", TextType.BOLD_TEXT)
        html_node = text_node_to_html_node(text_node)
        self.assertIsInstance(html_node, LeafNode)
        self.assertEqual(html_node.tag, "strong")
        self.assertEqual(html_node.value, "Bold Text")

    def test_text_node_to_html_node_italic(self):
        text_node = TextNode("Italic Text", TextType.ITALIC_TEXT)
        html_node = text_node_to_html_node(text_node)
        self.assertIsInstance(html_node, LeafNode)
        self.assertEqual(html_node.tag, "em")
        self.assertEqual(html_node.value, "Italic Text")
    
    def test_text_node_to_html_node_plain(self):
        text_node = TextNode("Plain Text", TextType.PLAIN_TEXT)
        html_node = text_node_to_html_node(text_node)
        self.assertIsInstance(html_node, LeafNode)
        self.assertIsNone(html_node.tag)
        self.assertEqual(html_node.value, "Plain Text")

    def test_text_node_to_html_node_code(self):
        text_node = TextNode("Code Text", TextType.CODE_TEXT)
        html_node = text_node_to_html_node(text_node)
        self.assertIsInstance(html_node, LeafNode)
        self.assertEqual(html_node.tag, "code")
        self.assertEqual(html_node.value, "Code Text")

    def test_text_node_to_html_node_link(self):
        text_node = TextNode("Link Text", TextType.LINKS, url="https://example.com")
        html_node = text_node_to_html_node(text_node)
        self.assertIsInstance(html_node, LeafNode)
        self.assertEqual(html_node.tag, "a")
        self.assertEqual(html_node.value, "Link Text")
        self.assertEqual(html_node.props, {"href": "https://example.com"})

    def test_text_node_to_html_node_link_no_url(self):
        text_node = TextNode("Link Text", TextType.LINKS)
        with self.assertRaises(ValueError):
            text_node_to_html_node(text_node)
   
    
if __name__ == "__main__":
    unittest.main()
    



