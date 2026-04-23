from enum import Enum
import re

class BlockType(Enum):
    PARAGRAPH = "paragraph"
    HEADER = "header"
    CODE = "code"
    QUOTE = "quote"
    UNORDERED_LIST = "unordered_list"
    ORDERED_LIST = "ordered_list"


def block_to_block_type(block):
    text = block.strip()

    if re.match(r"^#{1,6}\s+", text):
        return BlockType.HEADER
    if text.startswith("```") and text.endswith("```"):
        return BlockType.CODE
    if all(not l.strip() or re.match(r"^\s*>\s?.+", l) for l in block.splitlines()):
        return BlockType.QUOTE
    if all(not l.strip() or re.match(r"^\s*-\s+.+", l) for l in block.splitlines()):
        return BlockType.UNORDERED_LIST
    if all(not l.strip() or re.match(r"^\s*\d+\.\s+.+", l) for l in block.splitlines()):
        return BlockType.ORDERED_LIST
    return BlockType.PARAGRAPH