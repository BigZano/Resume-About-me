import unittest

from src.extract_markdown import extract_markdown_images, extract_markdown_links


class TestExtractMarkdown(unittest.TestCase):
        def test_extract_markdown_links(self):
            text = "This is text with a [link](https://example.com)"
            matches = extract_markdown_links(text)
            self.assertListEqual([("link", "https://example.com")], matches)

        def test_extract_markdown_images(self):
            text = "This is text with an ![image](https://i.imgur.com/image.png)"
            matches = extract_markdown_images(text)
            self.assertListEqual([("image", "https://i.imgur.com/image.png")], matches)



if __name__ == "__main__":
    unittest.main()
