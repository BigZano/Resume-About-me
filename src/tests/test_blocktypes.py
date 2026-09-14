import unittest

from src.block_types import BlockType, block_to_block_type


class TestBlockTypes(unittest.TestCase):
    def test_block_to_block_type(self):
        self.assertEqual(block_to_block_type("# Header 1"), BlockType.HEADER)
        self.assertEqual(block_to_block_type("## Header 2"), BlockType.HEADER)
        self.assertEqual(block_to_block_type("### Header 3"), BlockType.HEADER)
        self.assertEqual(block_to_block_type("#### Header 4"), BlockType.HEADER)
        self.assertEqual(block_to_block_type("##### Header 5"), BlockType.HEADER)
        self.assertEqual(block_to_block_type("###### Header 6"), BlockType.HEADER)
        self.assertEqual(block_to_block_type("> This is a quote"), BlockType.QUOTE)
        self.assertEqual(block_to_block_type("- List item"), BlockType.UNORDERED_LIST)
        self.assertEqual(block_to_block_type(". Ordered item"), BlockType.ORDERED_LIST)
        self.assertEqual(block_to_block_type("```code block```"), BlockType.CODE)
        self.assertEqual(block_to_block_type("This is a paragraph."), BlockType.PARAGRAPH)

if __name__ == '__main__':
    unittest.main()