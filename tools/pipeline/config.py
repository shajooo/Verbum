"""
Configuration, template schemas, and character definitions for Verbum Glyph Extraction.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class CharacterMeta:
    char: str
    category: str  # uppercase, lowercase, numbers, punctuation
    folder_name: str
    multi_component: bool = False
    is_small_punct: bool = False
    expected_components: int = 1


@dataclass
class GridBlockConfig:
    rows: List[CharacterMeta]
    row_count: int
    col_count: int = 14
    y_min_ratio: float = 0.0
    y_max_ratio: float = 1.0
    h_anchors: Optional[List[int]] = None
    v_anchors: Optional[List[int]] = None


@dataclass
class SheetTemplate:
    template_id: str
    description: str
    columns: int
    blocks: List[GridBlockConfig]
    deskew_angle: Optional[float] = None
    global_v_anchors: Optional[List[int]] = None

    @property
    def total_cells(self) -> int:
        return sum(b.row_count * b.col_count for b in self.blocks)


# Safe folder name mapping for all characters
CHAR_DEFINITIONS: Dict[str, CharacterMeta] = {
    # Lowercase a-z
    "a": CharacterMeta("a", "lowercase", "a"),
    "b": CharacterMeta("b", "lowercase", "b"),
    "c": CharacterMeta("c", "lowercase", "c"),
    "d": CharacterMeta("d", "lowercase", "d"),
    "e": CharacterMeta("e", "lowercase", "e"),
    "f": CharacterMeta("f", "lowercase", "f"),
    "g": CharacterMeta("g", "lowercase", "g"),
    "h": CharacterMeta("h", "lowercase", "h"),
    "i": CharacterMeta("i", "lowercase", "i", multi_component=True, expected_components=2),
    "j": CharacterMeta("j", "lowercase", "j", multi_component=True, expected_components=2),
    "k": CharacterMeta("k", "lowercase", "k"),
    "l": CharacterMeta("l", "lowercase", "l"),
    "m": CharacterMeta("m", "lowercase", "m"),
    "n": CharacterMeta("n", "lowercase", "n"),
    "o": CharacterMeta("o", "lowercase", "o"),
    "p": CharacterMeta("p", "lowercase", "p"),
    "q": CharacterMeta("q", "lowercase", "q"),
    "r": CharacterMeta("r", "lowercase", "r"),
    "s": CharacterMeta("s", "lowercase", "s"),
    "t": CharacterMeta("t", "lowercase", "t"),
    "u": CharacterMeta("u", "lowercase", "u"),
    "v": CharacterMeta("v", "lowercase", "v"),
    "w": CharacterMeta("w", "lowercase", "w"),
    "x": CharacterMeta("x", "lowercase", "x"),
    "y": CharacterMeta("y", "lowercase", "y"),
    "z": CharacterMeta("z", "lowercase", "z"),

    # Uppercase M-Z (and A-L for future template completeness)
    "A": CharacterMeta("A", "uppercase", "A"),
    "B": CharacterMeta("B", "uppercase", "B"),
    "C": CharacterMeta("C", "uppercase", "C"),
    "D": CharacterMeta("D", "uppercase", "D"),
    "E": CharacterMeta("E", "uppercase", "E"),
    "F": CharacterMeta("F", "uppercase", "F"),
    "G": CharacterMeta("G", "uppercase", "G"),
    "H": CharacterMeta("H", "uppercase", "H"),
    "I": CharacterMeta("I", "uppercase", "I"),
    "J": CharacterMeta("J", "uppercase", "J"),
    "K": CharacterMeta("K", "uppercase", "K"),
    "L": CharacterMeta("L", "uppercase", "L"),
    "M": CharacterMeta("M", "uppercase", "M"),
    "N": CharacterMeta("N", "uppercase", "N"),
    "O": CharacterMeta("O", "uppercase", "O"),
    "P": CharacterMeta("P", "uppercase", "P"),
    "Q": CharacterMeta("Q", "uppercase", "Q"),
    "R": CharacterMeta("R", "uppercase", "R"),
    "S": CharacterMeta("S", "uppercase", "S"),
    "T": CharacterMeta("T", "uppercase", "T"),
    "U": CharacterMeta("U", "uppercase", "U"),
    "V": CharacterMeta("V", "uppercase", "V"),
    "W": CharacterMeta("W", "uppercase", "W"),
    "X": CharacterMeta("X", "uppercase", "X"),
    "Y": CharacterMeta("Y", "uppercase", "Y"),
    "Z": CharacterMeta("Z", "uppercase", "Z"),

    # Numbers 0-9
    "0": CharacterMeta("0", "numbers", "0"),
    "1": CharacterMeta("1", "numbers", "1"),
    "2": CharacterMeta("2", "numbers", "2"),
    "3": CharacterMeta("3", "numbers", "3"),
    "4": CharacterMeta("4", "numbers", "4"),
    "5": CharacterMeta("5", "numbers", "5"),
    "6": CharacterMeta("6", "numbers", "6"),
    "7": CharacterMeta("7", "numbers", "7"),
    "8": CharacterMeta("8", "numbers", "8"),
    "9": CharacterMeta("9", "numbers", "9"),

    # Punctuation / symbols
    ".": CharacterMeta(".", "punctuation", "period", is_small_punct=True),
    ",": CharacterMeta(",", "punctuation", "comma", is_small_punct=True),
    ":": CharacterMeta(":", "punctuation", "colon", multi_component=True, is_small_punct=True, expected_components=2),
    "()": CharacterMeta("()", "punctuation", "parentheses", multi_component=True, expected_components=2),
    "{}": CharacterMeta("{}", "punctuation", "braces", multi_component=True, expected_components=2),
    "[]": CharacterMeta("[]", "punctuation", "brackets", multi_component=True, expected_components=2),
    "-": CharacterMeta("-", "punctuation", "hyphen", is_small_punct=True),
}


def get_template_for_sheet(file_name: str) -> SheetTemplate:
    """Returns the matching template configuration for a raw sheet."""
    base = Path(file_name).name
    
    # 1. Lowercase a-e (5 rows x 14 cols)
    if "media_1791224864942" in base or "lowercase_a_to_e" in base:
        chars = [CHAR_DEFINITIONS[c] for c in ["a", "b", "c", "d", "e"]]
        return SheetTemplate(
            template_id="lowercase_a_to_e",
            description="Lowercase letters a to e (5 rows x 14 columns)",
            columns=14,
            blocks=[GridBlockConfig(
                rows=chars,
                row_count=5,
                col_count=14,
                h_anchors=[14, 86, 159, 231, 294, 369]
            )],
            global_v_anchors=[0, 84, 164, 232, 314, 384, 453, 528, 613, 688, 762, 827, 897, 952, 1023]
        )

    # 2. Lowercase f-y (20 rows x 14 cols)
    if "media_1791224864924" in base or "lowercase_f_to_y" in base:
        letters = ["f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y"]
        chars = [CHAR_DEFINITIONS[c] for c in letters]
        return SheetTemplate(
            template_id="lowercase_f_to_y",
            description="Lowercase letters f to y (20 rows x 14 columns)",
            columns=14,
            blocks=[GridBlockConfig(
                rows=chars,
                row_count=20,
                col_count=14,
                h_anchors=[2, 57, 112, 166, 217, 275, 330, 382, 430, 475, 521, 569, 618, 668, 722, 773, 821, 870, 921, 973, 1023]
            )],
            global_v_anchors=[10, 63, 118, 167, 219, 268, 320, 371, 422, 473, 533, 589, 637, 685, 728]
        )

    # 3. Lowercase z (1 row x 14 cols)
    if "media_1791224864907" in base or "lowercase_z" in base:
        chars = [CHAR_DEFINITIONS["z"]]
        return SheetTemplate(
            template_id="lowercase_z",
            description="Lowercase letter z horizontal strip (1 row x 14 columns)",
            columns=14,
            blocks=[GridBlockConfig(
                rows=chars,
                row_count=1,
                col_count=14,
                h_anchors=[15, 90]
            )],
            deskew_angle=1.37,
            global_v_anchors=[22, 92, 162, 231, 307, 387, 453, 524, 596, 667, 737, 809, 877, 947, 1018]
        )

    # 4. Uppercase M-Z (14 rows x 14 cols)
    if "media_1791224864955" in base or "uppercase_m_to_z" in base:
        letters = ["M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"]
        chars = [CHAR_DEFINITIONS[c] for c in letters]
        return SheetTemplate(
            template_id="uppercase_m_to_z",
            description="Uppercase letters M to Z (14 rows x 14 columns)",
            columns=14,
            blocks=[GridBlockConfig(
                rows=chars,
                row_count=14,
                col_count=14,
                h_anchors=[2, 75, 148, 222, 296, 370, 444, 518, 592, 664, 736, 808, 880, 952, 1010]
            )],
            deskew_angle=-0.98,
            global_v_anchors=[8, 80, 154, 228, 302, 374, 446, 518, 590, 662, 736, 808, 880, 952, 1022]
        )

    # 5. Uppercase A-L (12 rows x 14 cols)
    if "media_1791228862843" in base or "uppercase_a_to_l" in base:
        letters = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
        chars = [CHAR_DEFINITIONS[c] for c in letters]
        return SheetTemplate(
            template_id="uppercase_a_to_l",
            description="Uppercase letters A to L (12 rows x 14 columns)",
            columns=14,
            blocks=[GridBlockConfig(
                rows=chars,
                row_count=12,
                col_count=14,
                h_anchors=[16, 83, 160, 230, 299, 372, 446, 523, 587, 664, 743, 821, 898]
            )],
            deskew_angle=-0.67,
            global_v_anchors=[12, 83, 154, 225, 306, 384, 451, 517, 586, 662, 737, 803, 883, 951, 1022]
        )

    # 6. Numbers 0-9 and Symbols (10 rows + 7 rows x 14 cols)
    if "media_1791224864875" in base or "numbers_and_symbols" in base:
        num_chars = [CHAR_DEFINITIONS[str(d)] for d in range(10)]
        sym_chars = [CHAR_DEFINITIONS[s] for s in [".", ",", ":", "()", "{}", "[]", "-"]]
        return SheetTemplate(
            template_id="numbers_and_symbols",
            description="Digits 0-9 (10 rows) and Symbols (7 rows) separated by divider gap",
            columns=14,
            blocks=[
                GridBlockConfig(
                    rows=num_chars,
                    row_count=10,
                    col_count=14,
                    h_anchors=[20, 72, 132, 196, 261, 321, 375, 425, 475, 530, 583]
                ),
                GridBlockConfig(
                    rows=sym_chars,
                    row_count=7,
                    col_count=14,
                    h_anchors=[640, 700, 752, 805, 857, 915, 968, 1020]
                )
            ],
            global_v_anchors=[6, 54, 108, 160, 212, 272, 327, 385, 442, 494, 550, 609, 667, 728, 800]
        )

    raise ValueError(f"No registered template for sheet file: {file_name}")


# Canonical list of raw sheet filenames
ALL_RAW_SHEET_NAMES = [
    "media_1791228862843.jpg",
    "media_1791224864955.jpg",
    "media_1791224864942.jpg",
    "media_1791224864924.jpg",
    "media_1791224864907.jpg",
    "media_1791224864875.jpg",
]

SHEET_TEMPLATES: Dict[str, SheetTemplate] = {name: get_template_for_sheet(name) for name in ALL_RAW_SHEET_NAMES}
TOTAL_EXPECTED_GLYPHS: int = sum(t.total_cells for t in SHEET_TEMPLATES.values())


def get_category_for_char(char: str) -> str:
    """Returns the category for a given character symbol."""
    if char in CHAR_DEFINITIONS:
        return CHAR_DEFINITIONS[char].category
    if char.isupper():
        return "uppercase"
    if char.islower():
        return "lowercase"
    if char.isdigit():
        return "numbers"
    return "punctuation"


def safe_char_filename(char: str) -> str:
    """Returns a safe filesystem folder or filename for a character."""
    if char in CHAR_DEFINITIONS:
        return CHAR_DEFINITIONS[char].folder_name
    return char.replace("/", "_").replace("\\", "_")
