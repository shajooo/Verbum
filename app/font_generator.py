"""
Verbum Font Generator — High-precision handwriting vectorizer and font builder.
Converts extracted 128x128 handwriting glyphs into standard installable TTF and OTF fonts.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont


logger = logging.getLogger(__name__)

# Typographic coordinate space (1000 unitsPerEm)
UNITS_PER_EM = 1000
CAP_HEIGHT = 700
X_HEIGHT = 490
ASCENDER_HEIGHT = 720
DESCENDER_DEPTH = -210
LINE_GAP = 200
DEFAULT_LSB = 55
DEFAULT_RSB = 55
SPACE_ADVANCE = 320


@dataclass
class DatasetValidationResult:
    is_valid: bool
    total_samples: int
    good_samples: int
    review_samples: int
    reject_samples: int
    uppercase_count: int
    lowercase_count: int
    numbers_count: int
    punctuation_count: int
    missing_characters: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SelectedGlyph:
    char: str
    category: str
    image_path: str
    glyph_id: str
    quality_score: float
    review_status: str
    is_split_component: Optional[str] = None  # "left" or "right" for paired punctuation


@dataclass
class FontBuildResult:
    success: bool
    ttf_path: Optional[str] = None
    otf_path: Optional[str] = None
    glyph_count: int = 0
    mapped_characters: List[str] = field(default_factory=list)
    validation_passed: bool = False
    validation_details: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


def get_character_vbounds(char: str, category: str) -> Tuple[int, int]:
    """
    Returns (font_y_bottom, font_y_top) for proper typographic alignment.
    Baseline is Y = 0.
    """
    if category in ("uppercase", "numbers"):
        return 0, CAP_HEIGHT

    if char in ("b", "d", "f", "h", "k", "l", "t"):
        return 0, ASCENDER_HEIGHT

    if char in ("g", "p", "q", "y"):
        return DESCENDER_DEPTH, X_HEIGHT

    if char == "j":
        return DESCENDER_DEPTH, ASCENDER_HEIGHT - 60  # dot near ascender, tail descends

    if char == "i":
        return 0, ASCENDER_HEIGHT - 60  # body sits on baseline, dot above x-height

    if category == "lowercase":
        return 0, X_HEIGHT

    # Punctuation / symbols
    if char == ".":
        return 0, 95
    if char == ",":
        return -55, 95
    if char == ":":
        return 0, X_HEIGHT - 20
    if char == "-":
        return int(X_HEIGHT * 0.42), int(X_HEIGHT * 0.58)
    if char in ("(", ")", "[", "]", "{", "}"):
        return -100, CAP_HEIGHT

    return 0, CAP_HEIGHT


def _character_category(char: str, manifest_category: str = "") -> str:
    """Use the Unicode label for metrics/coverage, not a staging-only category."""
    if len(char) == 1 and "A" <= char <= "Z":
        return "uppercase"
    if len(char) == 1 and "a" <= char <= "z":
        return "lowercase"
    if len(char) == 1 and char.isdigit():
        return "numbers"
    return manifest_category or "punctuation"


def _resolve_glyph_path(output_path: str, glyphs_dir: Path) -> Path:
    """Map a manifest entry to its equivalent file in the runtime glyph tree.

    Extraction manifests from earlier project iterations store absolute source
    paths.  The stable portion is the path below ``dataset/glyphs``; resolving
    from that suffix makes the same manifest usable from source and PyInstaller.
    """
    raw_path = Path(output_path)
    parts = raw_path.parts
    for index, part in enumerate(parts):
        if part.lower() == "glyphs":
            return glyphs_dir.joinpath(*parts[index + 1:])
    return glyphs_dir / raw_path.name


def validate_dataset(manifest_path: str | Path, glyphs_dir: str | Path) -> DatasetValidationResult:
    """
    Inspects manifest and filesystem to ensure full character coverage and sample validity.
    """
    manifest_p = Path(manifest_path)
    glyphs_p = Path(glyphs_dir)

    if not manifest_p.exists():
        return DatasetValidationResult(
            is_valid=False,
            total_samples=0,
            good_samples=0,
            review_samples=0,
            reject_samples=0,
            uppercase_count=0,
            lowercase_count=0,
            numbers_count=0,
            punctuation_count=0,
            missing_characters=["MANIFEST_NOT_FOUND"],
        )

    if not glyphs_p.is_dir():
        return DatasetValidationResult(
            is_valid=False,
            total_samples=0,
            good_samples=0,
            review_samples=0,
            reject_samples=0,
            uppercase_count=0,
            lowercase_count=0,
            numbers_count=0,
            punctuation_count=0,
            missing_characters=["GLYPH_DATASET_NOT_FOUND"],
        )

    try:
        with open(manifest_p, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
    except Exception as exc:
        logger.error("Failed to parse manifest JSON: %s", exc)
        return DatasetValidationResult(
            is_valid=False,
            total_samples=0,
            good_samples=0,
            review_samples=0,
            reject_samples=0,
            uppercase_count=0,
            lowercase_count=0,
            numbers_count=0,
            punctuation_count=0,
            missing_characters=["MANIFEST_CORRUPT"],
        )

    entries = manifest_data.get("entries", [])
    summary = manifest_data.get("summary", {})
    good_samples = summary.get("GOOD", 0)
    review_samples = summary.get("REVIEW", 0)
    reject_samples = summary.get("REJECT", 0)

    found_uppercase = set()
    found_lowercase = set()
    found_numbers = set()
    found_punct = set()

    for e in entries:
        ch = e.get("char", "")
        cat = _character_category(ch, e.get("category", ""))
        if cat == "uppercase":
            found_uppercase.add(ch)
        elif cat == "lowercase":
            found_lowercase.add(ch)
        elif cat == "numbers":
            found_numbers.add(ch)
        elif cat == "punctuation":
            found_punct.add(ch)

    expected_upper = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    expected_lower = [chr(c) for c in range(ord("a"), ord("z") + 1)]
    expected_nums = [str(n) for n in range(10)]

    missing = []
    for u in expected_upper:
        if u not in found_uppercase:
            missing.append(f"uppercase_{u}")
    for l in expected_lower:
        if l not in found_lowercase:
            missing.append(f"lowercase_{l}")
    for n in expected_nums:
        if n not in found_numbers:
            missing.append(f"number_{n}")
    # Punctuation is optional coverage: projects may legitimately collect a
    # different subset.  Every available punctuation glyph is still mapped.

    missing_files = [
        entry.get("glyph_id", entry.get("char", "unknown"))
        for entry in entries
        if not _resolve_glyph_path(entry.get("output_path", ""), glyphs_p).is_file()
    ]
    if missing_files:
        missing.append("GLYPH_FILES_NOT_FOUND")

    is_valid = len(missing) == 0 and len(entries) > 0

    return DatasetValidationResult(
        is_valid=is_valid,
        total_samples=len(entries),
        good_samples=good_samples,
        review_samples=review_samples,
        reject_samples=reject_samples,
        uppercase_count=len(found_uppercase),
        lowercase_count=len(found_lowercase),
        numbers_count=len(found_numbers),
        punctuation_count=len(found_punct),
        missing_characters=missing,
        details={
            "total_entries": len(entries),
            "manifest_version": manifest_data.get("version", "unknown"),
            "missing_glyph_files": missing_files,
        },
    )


def select_best_glyphs(manifest_path: str | Path, glyphs_dir: str | Path) -> Dict[str, SelectedGlyph]:
    """
    Selects one representative sample per character using quality score, contrast, and aspect ratio sanity.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    glyphs_p = Path(glyphs_dir)
    by_char: Dict[str, List[dict]] = {}
    for e in entries:
        # Rejected samples never become font input.  A REVIEW sample is usable
        # only when it is the best remaining candidate for that character.
        if e.get("review_status") not in ("GOOD", "REVIEW"):
            continue
        path = _resolve_glyph_path(e.get("output_path", ""), glyphs_p)
        if not path.is_file():
            continue
        ch = e.get("char", "")
        if not ch:
            continue
        by_char.setdefault(ch, []).append(e)

    selected: Dict[str, SelectedGlyph] = {}

    for ch, char_entries in by_char.items():
        # Score candidates: prefer GOOD, issues == NONE, high contrast, good blur score
        def score_candidate(item: dict) -> float:
            score = 0.0
            if item.get("review_status") == "GOOD":
                score += 1000.0
            if item.get("issues") == "NONE":
                score += 200.0
            score += float(item.get("contrast", 0.0))
            score += min(float(item.get("blur_variance", 0.0)), 300.0)
            return score

        char_entries.sort(key=lambda item: (score_candidate(item), str(item.get("glyph_id", ""))), reverse=True)
        best = char_entries[0]

        cat = _character_category(ch, best.get("category", ""))
        path_str = str(_resolve_glyph_path(best.get("output_path", ""), glyphs_p))

        # For paired punctuation, we register both characters from the same best cell
        if ch == "()":
            selected["("] = SelectedGlyph("(", cat, path_str, best.get("glyph_id", ""), best.get("quality_score", 1.0), best.get("review_status", "GOOD"), "left")
            selected[")"] = SelectedGlyph(")", cat, path_str, best.get("glyph_id", ""), best.get("quality_score", 1.0), best.get("review_status", "GOOD"), "right")
        elif ch == "[]":
            selected["["] = SelectedGlyph("[", cat, path_str, best.get("glyph_id", ""), best.get("quality_score", 1.0), best.get("review_status", "GOOD"), "left")
            selected["]"] = SelectedGlyph("]", cat, path_str, best.get("glyph_id", ""), best.get("quality_score", 1.0), best.get("review_status", "GOOD"), "right")
        elif ch == "{}":
            selected["{"] = SelectedGlyph("{", cat, path_str, best.get("glyph_id", ""), best.get("quality_score", 1.0), best.get("review_status", "GOOD"), "left")
            selected["}"] = SelectedGlyph("}", cat, path_str, best.get("glyph_id", ""), best.get("quality_score", 1.0), best.get("review_status", "GOOD"), "right")
        else:
            selected[ch] = SelectedGlyph(ch, cat, path_str, best.get("glyph_id", ""), best.get("quality_score", 1.0), best.get("review_status", "GOOD"), None)

    return selected


def _extract_glyph_binary(
    image_path: str,
    split_component: Optional[str] = None
) -> Tuple[Optional[np.ndarray], Tuple[int, int, int, int]]:
    """
    Loads normalized glyph image, thresholds ink, cleans specks, and handles split components.
    Returns: (cleaned_binary_mask, (ink_x_min, ink_y_min, ink_x_max, ink_y_max))
    """
    if not os.path.exists(image_path):
        return None, (0, 0, 0, 0)

    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None, (0, 0, 0, 0)

    # Threshold ink (ink is dark < 200, bg is 255)
    _, binary = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)

    if split_component in ("left", "right"):
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary)
        comps = []
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area > 25:
                comps.append((stats[i, cv2.CC_STAT_LEFT], i))
        comps.sort(key=lambda c: c[0])
        mask = np.zeros_like(binary)
        if len(comps) >= 2:
            target_idx = comps[0][1] if split_component == "left" else comps[-1][1]
            mask[labels == target_idx] = 255
        elif len(comps) == 1:
            mask[labels == comps[0][1]] = 255
        else:
            mask = binary
        binary = mask
    else:
        # Filter specks (< 20 px) unless it's small punctuation or solitary component
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary)
        if num_labels > 2:
            mask = np.zeros_like(binary)
            for i in range(1, num_labels):
                if stats[i, cv2.CC_STAT_AREA] >= 22:
                    mask[labels == i] = 255
            # If all components got wiped, revert to original
            if np.count_nonzero(mask) > 0:
                binary = mask

    ink_ys, ink_xs = np.where(binary > 0)
    if len(ink_ys) == 0:
        return None, (0, 0, 0, 0)

    x_min, x_max = int(ink_xs.min()), int(ink_xs.max())
    y_min, y_max = int(ink_ys.min()), int(ink_ys.max())
    return binary, (x_min, y_min, x_max, y_max)


def _compute_contour_signed_area(pts: List[Tuple[float, float]]) -> float:
    """Shoelace formula for polygon signed area."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for j in range(n):
        x1, y1 = pts[j]
        x2, y2 = pts[(j + 1) % n]
        area += (x1 * y2 - x2 * y1)
    return area * 0.5


def trace_glyph_outlines(
    binary: np.ndarray,
    char: str,
    category: str,
    ink_bbox: Tuple[int, int, int, int],
    use_spline: bool = True
) -> Tuple[List[List[Tuple[float, float]]], List[bool], int, int]:
    """
    Traces contours and transforms them into font coordinates with proper baseline alignment.
    Returns: (list_of_contours, list_of_is_hole, advance_width, left_side_bearing)
    """
    x_min, y_min, x_max, y_max = ink_bbox
    img_h = max(1, y_max - y_min + 1)
    img_w = max(1, x_max - x_min + 1)

    font_y_bottom, font_y_top = get_character_vbounds(char, category)
    target_font_h = font_y_top - font_y_bottom

    # Scale proportionally preserving natural aspect ratio
    scale = target_font_h / float(img_h)
    font_w = img_w * scale

    lsb = DEFAULT_LSB
    rsb = DEFAULT_RSB
    if char in (".", ",", ":", "'", '"'):
        lsb = int(DEFAULT_LSB * 0.7)
        rsb = int(DEFAULT_RSB * 0.7)

    advance_width = int(round(lsb + font_w + rsb))

    # Contour extraction with Teh-Chin k-cosine curvature approximation
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
    if hierarchy is None or len(contours) == 0:
        return [], [], advance_width, lsb

    fitted_contours: List[List[Tuple[float, float]]] = []
    is_holes: List[bool] = []

    for i, c in enumerate(contours):
        if cv2.contourArea(c) < 10:
            continue

        is_hole = bool(hierarchy[0][i][3] >= 0)

        # Polygon simplification with Douglas-Peucker (epsilon=0.65 preserves handwriting details)
        poly = cv2.approxPolyDP(c, 0.65, True).reshape(-1, 2)
        if len(poly) < 3:
            continue

        # Map to Font Coordinates: Y increases upwards, baseline is Y = 0
        font_pts: List[Tuple[float, float]] = []
        for px, py in poly:
            fx = lsb + (px - x_min) * scale
            fy = font_y_bottom + (y_max - py) * scale
            font_pts.append((round(fx, 1), round(fy, 1)))

        signed_area = _compute_contour_signed_area(font_pts)
        # In TrueType standard:
        # Outer contours must be clockwise (signed_area < 0 in standard Cartesian coordinates where Y points up)
        # Holes must be counter-clockwise (signed_area > 0)
        if not is_hole and signed_area > 0:
            font_pts.reverse()
        elif is_hole and signed_area < 0:
            font_pts.reverse()

        fitted_contours.append(font_pts)
        is_holes.append(is_hole)

    return fitted_contours, is_holes, advance_width, lsb


def build_notdef_glyph() -> Tuple[Any, int, int]:
    """Generates standard .notdef glyph rectangle."""
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((100, CAP_HEIGHT))
    pen.lineTo((500, CAP_HEIGHT))
    pen.lineTo((500, 0))
    pen.closePath()
    pen.moveTo((150, 50))
    pen.lineTo((450, 50))
    pen.lineTo((450, CAP_HEIGHT - 50))
    pen.lineTo((150, CAP_HEIGHT - 50))
    pen.closePath()
    return pen.glyph(), 600, 100


def build_space_glyph() -> Tuple[Any, int, int]:
    """Generates space glyph with advance width."""
    pen = TTGlyphPen(None)
    return pen.glyph(), SPACE_ADVANCE, 0


def create_handwriting_font(
    manifest_path: str | Path,
    glyphs_dir: str | Path,
    output_dir: str | Path,
    font_name: str = "Verbum Handwriting",
    build_otf: bool = True,
    progress_cb: Optional[Callable[[str, float], None]] = None
) -> FontBuildResult:
    """
    Main font generation pipeline.
    Produces valid installable TrueType (.ttf) and OpenType (.otf) files.
    """
    manifest_p = Path(manifest_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if progress_cb:
        progress_cb("Validating dataset...", 0.05)

    validation = validate_dataset(manifest_p, glyphs_dir)
    if not validation.is_valid:
        msg = f"Dataset validation failed: missing {', '.join(validation.missing_characters)}"
        logger.error(msg)
        return FontBuildResult(success=False, error_message=msg)

    if progress_cb:
        progress_cb("Selecting best glyph samples...", 0.15)

    selected_glyphs = select_best_glyphs(manifest_p, glyphs_dir)
    logger.info("Selected %d character samples for font generation", len(selected_glyphs))

    # Standard glyph naming mapping
    def get_glyph_name(char: str) -> str:
        if char == " ":
            return "space"
        if char == ".":
            return "period"
        if char == ",":
            return "comma"
        if char == ":":
            return "colon"
        if char == "-":
            return "hyphen"
        if char == "(":
            return "parenleft"
        if char == ")":
            return "parenright"
        if char == "[":
            return "bracketleft"
        if char == "]":
            return "bracketright"
        if char == "{":
            return "braceleft"
        if char == "}":
            return "braceright"
        if char.isdigit():
            names = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
            return names[int(char)]
        if char.isalpha():
            return char
        return f"uni{ord(char):04X}"

    glyph_order = [".notdef", "space"]
    cmap: Dict[int, str] = {32: "space"}

    for ch in sorted(selected_glyphs.keys()):
        g_name = get_glyph_name(ch)
        if g_name not in glyph_order:
            glyph_order.append(g_name)
        cmap[ord(ch)] = g_name

    # FontBuilder initialization for TrueType
    fb_ttf = FontBuilder(UNITS_PER_EM, isTTF=True)
    fb_ttf.setupGlyphOrder(glyph_order)
    fb_ttf.setupCharacterMap(cmap)

    ttf_glyphs: Dict[str, Any] = {}
    cff_charstrings: Dict[str, Any] = {}
    hmetrics: Dict[str, Tuple[int, int]] = {}

    notdef_g, notdef_w, notdef_lsb = build_notdef_glyph()
    ttf_glyphs[".notdef"] = notdef_g
    hmetrics[".notdef"] = (notdef_w, notdef_lsb)

    space_g, space_w, space_lsb = build_space_glyph()
    ttf_glyphs["space"] = space_g
    hmetrics["space"] = (space_w, space_lsb)

    # For CFF Pen
    cff_pen_notdef = T2CharStringPen(notdef_w, None)
    cff_pen_notdef.moveTo((100, 0))
    cff_pen_notdef.lineTo((100, CAP_HEIGHT))
    cff_pen_notdef.lineTo((500, CAP_HEIGHT))
    cff_pen_notdef.lineTo((500, 0))
    cff_pen_notdef.closePath()
    cff_charstrings[".notdef"] = cff_pen_notdef.getCharString()

    cff_pen_space = T2CharStringPen(space_w, None)
    cff_charstrings["space"] = cff_pen_space.getCharString()

    total_chars = len(selected_glyphs)
    for idx, (ch, selected) in enumerate(selected_glyphs.items()):
        if progress_cb:
            pct = 0.20 + (idx / float(total_chars)) * 0.55
            progress_cb(f"Vectorizing glyph '{ch}' ({idx+1}/{total_chars})...", pct)

        g_name = get_glyph_name(ch)
        binary, ink_bbox = _extract_glyph_binary(selected.image_path, selected.is_split_component)

        if binary is None:
            return FontBuildResult(success=False, error_message=f"Selected glyph '{ch}' is empty or unreadable.")

        contours, is_holes, advance_w, lsb = trace_glyph_outlines(
            binary, ch, selected.category, ink_bbox, use_spline=True
        )
        if not contours:
            return FontBuildResult(success=False, error_message=f"Could not trace a usable outline for '{ch}'.")

        # Draw TrueType outlines with quadratic spline midpoints
        tt_pen = TTGlyphPen(None)
        cff_pen = T2CharStringPen(advance_w, None)

        for font_pts, is_hole in zip(contours, is_holes):
            if len(font_pts) < 3:
                continue

            # TTF TrueType quadratic curve drawing
            tt_pen.moveTo(font_pts[0])
            for j in range(len(font_pts)):
                p_curr = font_pts[j]
                p_next = font_pts[(j + 1) % len(font_pts)]
                mid = (round((p_curr[0] + p_next[0]) * 0.5, 1), round((p_curr[1] + p_next[1]) * 0.5, 1))
                tt_pen.qCurveTo(p_curr, mid)
            tt_pen.closePath()

            # CFF OTF cubic curve drawing
            # For CFF, outer contours must be counter-clockwise, holes clockwise (reverse of TrueType)
            cff_pts = list(font_pts)
            cff_pts.reverse()
            cff_pen.moveTo(cff_pts[0])
            for pt in cff_pts[1:]:
                cff_pen.lineTo(pt)
            cff_pen.closePath()

        ttf_glyphs[g_name] = tt_pen.glyph()
        cff_charstrings[g_name] = cff_pen.getCharString()
        hmetrics[g_name] = (advance_w, lsb)

    if progress_cb:
        progress_cb("Constructing font tables...", 0.80)

    # 1. Setup TTF
    fb_ttf.setupGlyf(ttf_glyphs)
    fb_ttf.setupHorizontalMetrics(hmetrics)
    fb_ttf.setupHorizontalHeader(ascent=800, descent=DESCENDER_DEPTH, lineGap=LINE_GAP)
    
    ps_name = font_name.replace(" ", "") + "-Regular"
    name_strings = {
        "familyName": font_name,
        "styleName": "Regular",
        "psName": ps_name,
        "fullName": font_name,
        "uniqueFontIdentifier": f"1.000;VRBM;{ps_name}",
        "version": "Version 1.000",
    }
    fb_ttf.setupNameTable(name_strings)
    fb_ttf.setupOS2(
        sTypoAscender=800,
        sTypoDescender=DESCENDER_DEPTH,
        sTypoLineGap=LINE_GAP,
        usWinAscent=1000,
        usWinDescent=abs(DESCENDER_DEPTH),
        sxHeight=X_HEIGHT,
        sCapHeight=CAP_HEIGHT,
        fsType=0,  # Installable embedding
    )
    fb_ttf.setupPost()

    clean_filename = font_name.replace(" ", "_")
    ttf_out_path = out_dir / f"{clean_filename}.ttf"
    fb_ttf.save(str(ttf_out_path))
    logger.info("Saved TrueType font: %s", ttf_out_path)

    # 2. Setup OTF
    otf_out_path = None
    if build_otf:
        try:
            fb_otf = FontBuilder(UNITS_PER_EM, isTTF=False)
            fb_otf.setupGlyphOrder(glyph_order)
            fb_otf.setupCharacterMap(cmap)
            fb_otf.setupCFF(
                psName=ps_name,
                fontInfo={"FullName": font_name, "FamilyName": font_name, "Weight": "Regular"},
                charStringsDict=cff_charstrings,
                privateDict={},
            )
            fb_otf.setupHorizontalMetrics(hmetrics)
            fb_otf.setupHorizontalHeader(ascent=800, descent=DESCENDER_DEPTH, lineGap=LINE_GAP)
            fb_otf.setupNameTable(name_strings)
            fb_otf.setupOS2(
                sTypoAscender=800,
                sTypoDescender=DESCENDER_DEPTH,
                sTypoLineGap=LINE_GAP,
                usWinAscent=1000,
                usWinDescent=abs(DESCENDER_DEPTH),
                sxHeight=X_HEIGHT,
                sCapHeight=CAP_HEIGHT,
                fsType=0,
            )
            fb_otf.setupPost()
            otf_out_path = out_dir / f"{clean_filename}.otf"
            fb_otf.save(str(otf_out_path))
            logger.info("Saved OpenType font: %s", otf_out_path)
        except Exception as otf_exc:
            logger.warning("OTF generation encountered error: %s (TTF remains valid)", otf_exc)
            otf_out_path = None

    if progress_cb:
        progress_cb("Validating generated font...", 0.90)

    # Font validation with fontTools
    val_ok, val_details = validate_font_file(ttf_out_path, list(cmap.keys()))
    if not val_ok:
        logger.error("Generated font failed validation: %s", val_details)
        return FontBuildResult(
            success=False,
            ttf_path=str(ttf_out_path),
            validation_passed=False,
            validation_details=val_details,
            error_message="Font table validation failed.",
        )

    if otf_out_path is not None:
        otf_ok, otf_details = validate_font_file(otf_out_path, list(cmap.keys()), is_otf=True)
        val_details["otf"] = otf_details
        if not otf_ok:
            logger.warning("Generated OTF failed validation and will not be published: %s", otf_details)
            otf_out_path.unlink(missing_ok=True)
            otf_out_path = None

    if progress_cb:
        progress_cb("Font ready!", 1.0)

    return FontBuildResult(
        success=True,
        ttf_path=str(ttf_out_path),
        otf_path=str(otf_out_path) if otf_out_path else None,
        glyph_count=len(glyph_order),
        mapped_characters=[chr(c) for c in sorted(cmap.keys()) if c != 32],
        validation_passed=True,
        validation_details=val_details,
    )


def validate_font_file(
    font_path: str | Path, expected_codepoints: List[int], *, is_otf: bool = False
) -> Tuple[bool, Dict[str, Any]]:
    """
    Parses and verifies font table completeness, character mapping, and outlines.
    """
    details: Dict[str, Any] = {}
    try:
        font = TTFont(str(font_path))
        tables = list(font.keys())
        details["tables"] = tables

        required_tables = ["head", "hhea", "maxp", "OS/2", "name", "cmap", "post", "hmtx"]
        required_tables.append("CFF " if is_otf else "glyf")
        missing = [t for t in required_tables if t not in tables]
        if missing:
            details["missing_tables"] = missing
            return False, details

        # Verify cmap
        best_cmap = font.getBestCmap()
        if not best_cmap:
            details["error"] = "No valid Unicode cmap subtable found"
            return False, details

        missing_chars = [chr(cp) for cp in expected_codepoints if cp not in best_cmap]
        details["mapped_count"] = len(best_cmap)
        details["missing_chars"] = missing_chars
        if missing_chars:
            details["error"] = f"Missing {len(missing_chars)} expected codepoints in cmap"
            return False, details

        names = {record.toUnicode() for record in font["name"].names if record.nameID in (1, 4, 6)}
        if not any(name.strip() for name in names):
            details["error"] = "Font has no usable family/full/PostScript name"
            return False, details

        glyph_set = font.getGlyphSet()
        empty = []
        for codepoint in expected_codepoints:
            glyph_name = best_cmap[codepoint]
            if glyph_name == "space":
                continue
            glyph = glyph_set[glyph_name]
            if getattr(glyph, "width", 0) <= 0:
                empty.append(glyph_name)
        if empty:
            details["empty_or_invalid_metrics"] = empty
            return False, details

        font.close()
        return True, details
    except Exception as exc:
        details["exception"] = str(exc)
        return False, details


def render_font_preview_specimen(
    font_path: str | Path,
    output_image_path: str | Path,
    font_size: int = 32
) -> str:
    """
    Renders visual font specimen card showing uppercase, lowercase, numbers, punctuation,
    and realistic paragraph text to an image.
    """
    font_p = Path(font_path)
    out_img = Path(output_image_path)
    out_img.parent.mkdir(parents=True, exist_ok=True)

    img_w, img_h = 920, 540
    img = Image.new("RGB", (img_w, img_h), "#12141c")
    draw = ImageDraw.Draw(img)

    try:
        hw_font_lg = ImageFont.truetype(str(font_p), 34)
        hw_font_md = ImageFont.truetype(str(font_p), 26)
        hw_font_sm = ImageFont.truetype(str(font_p), 22)
    except Exception as exc:
        logger.error("Failed to load font for rendering preview: %s", exc)
        return ""

    # Header
    draw.text((36, 28), "Verbum Handwriting Specimen", fill="#9084ff")
    draw.line([(36, 62), (img_w - 36, 62)], fill="#292d40", width=1)

    # 1. Uppercase & Lowercase lines
    y = 80
    draw.text((36, y), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", font=hw_font_lg, fill="#ffffff")
    y += 52
    draw.text((36, y), "abcdefghijklmnopqrstuvwxyz", font=hw_font_lg, fill="#e2e0f5")
    y += 52

    # 2. Digits & Punctuation
    draw.text((36, y), "0123456789  . , : - ( ) [ ] { }", font=hw_font_md, fill="#c5c0f0")
    y += 48
    draw.line([(36, y), (img_w - 36, y)], fill="#292d40", width=1)
    y += 20

    # 3. Natural Paragraph Sample
    draw.text((36, y), "The quick brown fox jumps over the lazy dog.", font=hw_font_md, fill="#ffffff")
    y += 44
    draw.text((36, y), "Today's Plan:", font=hw_font_sm, fill="#989bb0")
    y += 34
    draw.text((36, y), "Finish college assignment", font=hw_font_sm, fill="#989bb0")
    y += 30
    draw.text((36, y), "Study Data Structures", font=hw_font_sm, fill="#989bb0")
    y += 30
    draw.text((36, y), "Work on Verbum.", font=hw_font_sm, fill="#989bb0")

    img.save(str(out_img))
    logger.info("Rendered font preview specimen: %s", out_img)
    return str(out_img)
