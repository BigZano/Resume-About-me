import unittest

from Gen_Content import extract_title_markdown


class TestExtractTitleMarkdown(unittest.TestCase):
    def test_extract_title(self):
        md = """# My Title"""
        title = extract_title_markdown.extract_title(md)
        assert title == "My Title"

    def test_ignores_non_h1_and_whitespace(self):
        md = """### slslkdi\n # This is my title\n ## someother bs"""
        title = extract_title_markdown.extract_title(md)
        assert title == "This is my title"

    def test_no_title(self):
        md ="""### slslkdi\n ## someother bs"""
        try:
            extract_title_markdown.extract_title(md)
        except ValueError as e:
            assert str(e) == "No title found in markdown"


if __name__ == "__main__":
    unittest.main()