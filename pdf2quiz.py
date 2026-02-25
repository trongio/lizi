#!/usr/bin/env python3
"""
pdf2quiz.py - Convert Georgian quiz PDFs to JSON format for the quiz app.

Extracts questions, options, and correct answers (yellow-highlighted) from
PDF files generated from Word documents with teal header bars.

Usage:
    python3 pdf2quiz.py path/to/quiz.pdf

Output:
    - path/to/quiz.json          (raw JSON data)
    - path/to/quiz.js            (window.QUIZ_DATA = ... wrapper)
    - path/to/quiz_images/       (extracted images, if any)

Requirements:
    pip install PyMuPDF
"""

import sys
import re
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF is not installed.")
    print()
    print("Install it with:")
    print("  pip install PyMuPDF")
    print()
    print("Or if you get a PEP 668 error on newer systems:")
    print("  pip install --break-system-packages PyMuPDF")
    print("  # or use a virtual environment:")
    print("  python3 -m venv .venv && source .venv/bin/activate && pip install PyMuPDF")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger("pdf2quiz")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Georgian option prefixes: ა) ბ) გ) დ) ე)
GEORGIAN_OPTION_LETTERS = ["ა", "ბ", "გ", "დ", "ე"]
# Latin option prefixes: a) b) c) d) e) (some PDFs use these)
LATIN_OPTION_LETTERS = ["a", "b", "c", "d", "e"]

# Regex patterns for option detection (Georgian and Latin)
OPTION_PATTERN_KA = re.compile(r"^([ა-ე])\)\s*(.+)")
OPTION_PATTERN_LA = re.compile(r"^([a-eA-E])\)\s*(.+)")

# Teal/green header bar color (approximate RGB: 0.01, 0.47, 0.49)
TEAL_COLOR_THRESHOLD = {
    "r_max": 0.15,
    "g_min": 0.35,
    "g_max": 0.60,
    "b_min": 0.35,
    "b_max": 0.60,
}

# Yellow highlight color: high R, high G, low B
YELLOW_THRESHOLD = {
    "r_min": 0.85,
    "g_min": 0.85,
    "b_max": 0.30,
}


# ---------------------------------------------------------------------------
# Color detection helpers
# ---------------------------------------------------------------------------
def is_teal_fill(fill):
    """Check if a fill color tuple (r,g,b) matches the teal header bar."""
    if not fill:
        return False
    r, g, b = fill
    return (
        r <= TEAL_COLOR_THRESHOLD["r_max"]
        and TEAL_COLOR_THRESHOLD["g_min"] <= g <= TEAL_COLOR_THRESHOLD["g_max"]
        and TEAL_COLOR_THRESHOLD["b_min"] <= b <= TEAL_COLOR_THRESHOLD["b_max"]
    )


def is_yellow_fill(fill):
    """Check if a fill color tuple (r,g,b) is yellow highlight."""
    if not fill:
        return False
    r, g, b = fill
    return (
        r >= YELLOW_THRESHOLD["r_min"]
        and g >= YELLOW_THRESHOLD["g_min"]
        and b <= YELLOW_THRESHOLD["b_max"]
    )


# ---------------------------------------------------------------------------
# PDF analysis
# ---------------------------------------------------------------------------
def find_teal_header_rects(page):
    """Find all teal header bar rectangles on a page, return list of (rect, question_number)."""
    headers = []
    drawings = page.get_drawings()
    for d in drawings:
        fill = d.get("fill")
        if is_teal_fill(fill):
            rect = d["rect"]
            text = page.get_text("text", clip=rect).strip()
            # The text inside teal bars is the question number
            try:
                q_num = int(text)
                headers.append((rect, q_num))
            except ValueError:
                log.warning(
                    "Teal header found but text is not a number: '%s' on page %d",
                    text,
                    page.number + 1,
                )
    # Sort by vertical position (top of rect)
    headers.sort(key=lambda h: h[0].y0)
    return headers


def find_yellow_highlights(page):
    """Find all yellow highlight rectangles, return list of (rect, highlighted_text)."""
    highlights = []
    drawings = page.get_drawings()
    for d in drawings:
        fill = d.get("fill")
        if is_yellow_fill(fill):
            rect = d["rect"]
            text = page.get_text("text", clip=rect).strip()
            if text:
                highlights.append((rect, text))

    # Also check highlight annotations (some PDFs use annotation-based highlights)
    if page.annots():
        for annot in page.annots():
            # Highlight annotation type = 8
            if annot.type[0] == 8:
                rect = annot.rect
                text = page.get_text("text", clip=rect).strip()
                if text:
                    # Check if annotation color is yellow-ish
                    colors = annot.colors
                    stroke = colors.get("stroke")
                    fill_c = colors.get("fill")
                    c = fill_c or stroke
                    if c and len(c) >= 3 and is_yellow_fill(c[:3]):
                        highlights.append((rect, text))

    return highlights


def find_images_on_page(page):
    """Find image blocks on the page, return list of (bbox, image_index)."""
    images = []
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        if block["type"] == 1:  # image block
            bbox = fitz.Rect(block["bbox"])
            images.append(bbox)
    return images


def extract_image_for_question(page, doc, image_bbox, q_num, output_dir):
    """Extract an image near a question and save it to disk."""
    # Render the page region as a pixmap
    clip = fitz.Rect(image_bbox)
    # Use a reasonable zoom for quality
    zoom = 2.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip)

    img_dir = output_dir / "images"
    img_dir.mkdir(exist_ok=True)
    img_path = img_dir / f"q{q_num}.png"
    pix.save(str(img_path))
    log.info("  Saved image for Q%d: %s", q_num, img_path.name)
    return f"images/q{q_num}.png"


# ---------------------------------------------------------------------------
# Text parsing
# ---------------------------------------------------------------------------
def detect_option_style(all_text):
    """Detect whether the PDF uses Georgian (ა,ბ,გ,დ,ე) or Latin (a,b,c,d,e) option labels."""
    ka_count = len(re.findall(r"[ა-ე]\)", all_text))
    la_count = len(re.findall(r"[a-eA-E]\)", all_text))
    if ka_count >= la_count:
        return "ka"
    return "la"


def get_option_letter_index(letter, style):
    """Convert an option letter to 0-based index."""
    letters = GEORGIAN_OPTION_LETTERS if style == "ka" else LATIN_OPTION_LETTERS
    letter_lower = letter.lower()
    try:
        return letters.index(letter_lower)
    except ValueError:
        # For Georgian letters, they might not be in the list directly
        # Map Georgian letters ა=0, ბ=1, გ=2, დ=3, ე=4
        ka_map = {"ა": 0, "ბ": 1, "გ": 2, "დ": 3, "ე": 4}
        la_map = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}
        m = ka_map if style == "ka" else la_map
        return m.get(letter_lower, -1)


def parse_option_text(text, style):
    """Try to parse an option letter and text from a string.
    Returns (letter, option_text) or None."""
    pattern = OPTION_PATTERN_KA if style == "ka" else OPTION_PATTERN_LA
    m = pattern.match(text.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return None


def clean_text(text):
    """Clean extracted text: normalize whitespace, strip."""
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Question extraction - region-based approach
# ---------------------------------------------------------------------------
def get_question_regions(page, headers, page_height):
    """Given sorted headers on a page, compute the vertical region for each question.
    Returns list of (q_num, top_y, bottom_y)."""
    regions = []
    for i, (rect, q_num) in enumerate(headers):
        top_y = rect.y0
        if i + 1 < len(headers):
            bottom_y = headers[i + 1][0].y0
        else:
            bottom_y = page_height
        regions.append((q_num, top_y, bottom_y))
    return regions


def extract_text_in_region(page, top_y, bottom_y, page_width):
    """Extract all text lines in a vertical region of the page."""
    clip = fitz.Rect(0, top_y, page_width, bottom_y)
    # Use "dict" mode for detailed span info
    blocks = page.get_text("dict", clip=clip)["blocks"]
    lines = []
    for block in blocks:
        if block["type"] == 0:  # text block
            for line in block["lines"]:
                line_text = ""
                for span in line["spans"]:
                    line_text += span["text"]
                line_text = line_text.strip()
                if line_text:
                    lines.append(line_text)
    return lines


def parse_question_from_lines(lines, style):
    """Parse question text and options from extracted text lines.
    Returns (question_text, options_list) where options_list is list of (index, text)."""
    question_lines = []
    options = []
    in_options = False

    for line in lines:
        # Try to detect if this line starts one or more options
        # Some PDFs have multiple options on one line separated by spaces
        parsed = try_parse_options_from_line(line, style)
        if parsed:
            in_options = True
            options.extend(parsed)
        elif in_options:
            # This might be a continuation of the last option
            if options:
                last_idx, last_text = options[-1]
                options[-1] = (last_idx, last_text + " " + line)
        else:
            question_lines.append(line)

    question_text = clean_text(" ".join(question_lines))
    # Clean up option texts
    cleaned_options = [(idx, clean_text(text)) for idx, text in options]
    return question_text, cleaned_options


def try_parse_options_from_line(line, style):
    """Try to parse one or more options from a single line.
    Returns list of (letter_index, text) or None if no options found."""
    if style == "ka":
        # Georgian pattern: ა) text  ბ) text  გ) text
        parts = re.split(r"(?<!\S)([ა-ე])\)\s*", line)
    else:
        # Latin pattern: a) text  b) text  c) text
        parts = re.split(r"(?<!\S)([a-eA-E])\)\s*", line)

    if len(parts) < 3:
        # No option pattern found
        return None

    results = []
    # parts[0] is text before first option (should be empty or whitespace)
    # parts[1] is letter, parts[2] is text, parts[3] is letter, parts[4] is text, ...
    i = 1
    while i < len(parts) - 1:
        letter = parts[i]
        text = parts[i + 1].strip()
        idx = get_option_letter_index(letter, style)
        if idx >= 0 and text:
            results.append((idx, text))
        elif idx >= 0:
            results.append((idx, ""))
        i += 2

    return results if results else None


# ---------------------------------------------------------------------------
# Answer detection via yellow highlights
# ---------------------------------------------------------------------------
def match_highlight_to_option(highlight_text, options, style):
    """Given yellow-highlighted text, find which option index it matches.
    Returns 0-based option index or -1."""
    ht = clean_text(highlight_text)

    # First try: highlighted text starts with an option letter like "გ) ოქრო"
    parsed = parse_option_text(ht, style)
    if parsed:
        letter, _ = parsed
        idx = get_option_letter_index(letter, style)
        if 0 <= idx < len(options):
            return idx

    # Second try: match highlighted text content against option texts
    for i, (_, opt_text) in enumerate(options):
        if not opt_text:
            continue
        # Check if highlighted text contains the option text or vice versa
        if opt_text in ht or ht in opt_text:
            return i
        # Fuzzy: check if first 15 chars match
        if len(opt_text) > 5 and len(ht) > 5:
            if opt_text[:15] in ht or ht[:15] in opt_text:
                return i

    return -1


def find_answer_for_question(
    page, yellow_highlights, q_top_y, q_bottom_y, options, style
):
    """Find the correct answer for a question by matching yellow highlights
    that fall within the question's vertical region."""
    for rect, hl_text in yellow_highlights:
        # Check if highlight is within this question's region
        hl_center_y = (rect.y0 + rect.y1) / 2
        if q_top_y <= hl_center_y <= q_bottom_y:
            idx = match_highlight_to_option(hl_text, options, style)
            if idx >= 0:
                return idx, hl_text
            else:
                log.warning(
                    "  Yellow highlight found but couldn't match to option: '%s'",
                    hl_text[:60],
                )
                # Try returning the raw highlight for manual review
                return -1, hl_text
    return -1, None


# ---------------------------------------------------------------------------
# Image association
# ---------------------------------------------------------------------------
def find_image_for_question(image_bboxes, q_top_y, q_bottom_y):
    """Check if any image falls within a question's region."""
    for bbox in image_bboxes:
        img_center_y = (bbox.y0 + bbox.y1) / 2
        if q_top_y <= img_center_y <= q_bottom_y:
            return bbox
    return None


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------
def extract_quiz(pdf_path):
    """Extract quiz data from a PDF file. Returns a dict with title and questions."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        log.error("File not found: %s", pdf_path)
        sys.exit(1)

    doc = fitz.open(str(pdf_path))
    log.info("Opened: %s (%d pages)", pdf_path.name, doc.page_count)

    # Derive title from filename
    title = pdf_path.stem
    # Remove common suffixes like .docx
    title = re.sub(r"\.docx$", "", title, flags=re.IGNORECASE)
    # Replace hyphens/underscores with spaces for readability
    title_display = title.replace("-", " ").replace("_", " ").strip()

    # Detect option style by scanning full text
    full_text = ""
    for page in doc:
        full_text += page.get_text("text")
    style = detect_option_style(full_text)
    log.info("Detected option style: %s", "Georgian (ა,ბ,გ,დ,ე)" if style == "ka" else "Latin (a,b,c,d,e)")

    output_dir = pdf_path.parent

    questions = []
    # Track questions that span pages (text continues on next page)
    pending_question = None  # (q_num, top_y on next page)

    # First pass: collect all questions across all pages
    all_page_data = []
    for page_num in range(doc.page_count):
        page = doc[page_num]
        page_width = page.rect.width
        page_height = page.rect.height

        headers = find_teal_header_rects(page)
        yellow_highlights = find_yellow_highlights(page)
        image_bboxes = find_images_on_page(page)

        all_page_data.append({
            "page": page,
            "page_num": page_num,
            "headers": headers,
            "yellow_highlights": yellow_highlights,
            "image_bboxes": image_bboxes,
            "page_width": page_width,
            "page_height": page_height,
        })

    # Second pass: extract questions, handling cross-page continuations
    for pi, pd in enumerate(all_page_data):
        page = pd["page"]
        headers = pd["headers"]
        yellow_highlights = pd["yellow_highlights"]
        image_bboxes = pd["image_bboxes"]
        page_width = pd["page_width"]
        page_height = pd["page_height"]
        page_num = pd["page_num"]

        if not headers and not pending_question:
            # Page with no headers and no pending question - might be continuation
            # Check if there's a pending question from previous page
            continue

        # If there's a pending question from the previous page and this page has
        # no header at the very top, the top region belongs to the pending question
        continuation_bottom = 0
        if pending_question is not None:
            pq_num = pending_question
            if headers:
                continuation_bottom = headers[0][0].y0
            else:
                continuation_bottom = page_height

            # Extract continuation text
            cont_lines = extract_text_in_region(page, 0, continuation_bottom, page_width)
            # Find highlights in continuation region
            answer_idx, hl_text = find_answer_for_question(
                page, yellow_highlights, 0, continuation_bottom, [], style
            )

            # Append continuation to the last question
            if questions and questions[-1]["id"] == pq_num:
                # Parse the continuation for additional options or text
                cont_parsed_opts = []
                cont_question_lines = []
                for line in cont_lines:
                    parsed = try_parse_options_from_line(line, style)
                    if parsed:
                        cont_parsed_opts.extend(parsed)
                    elif cont_parsed_opts:
                        # continuation of last option
                        last_idx, last_text = cont_parsed_opts[-1]
                        cont_parsed_opts[-1] = (last_idx, last_text + " " + line)
                    else:
                        cont_question_lines.append(line)

                # Merge continuation text into question
                if cont_question_lines:
                    existing_text = questions[-1]["text"]
                    questions[-1]["text"] = clean_text(
                        existing_text + " " + " ".join(cont_question_lines)
                    )

                # Merge continuation options
                existing_options = questions[-1]["options"]
                for idx, text in cont_parsed_opts:
                    while len(existing_options) <= idx:
                        existing_options.append("")
                    if existing_options[idx] == "":
                        existing_options[idx] = clean_text(text)
                    else:
                        existing_options[idx] = clean_text(
                            existing_options[idx] + " " + text
                        )

                # Re-check answer with merged options
                if questions[-1]["answer"] == -1:
                    merged_opts = [(i, t) for i, t in enumerate(existing_options)]
                    ans_idx, ans_text = find_answer_for_question(
                        page, yellow_highlights, 0, continuation_bottom,
                        merged_opts, style
                    )
                    if ans_idx >= 0:
                        questions[-1]["answer"] = ans_idx

                # Check for image in continuation
                img_bbox = find_image_for_question(image_bboxes, 0, continuation_bottom)
                if img_bbox and not questions[-1].get("image"):
                    img_path = extract_image_for_question(
                        page, doc, img_bbox, pq_num, output_dir
                    )
                    questions[-1]["image"] = img_path

            pending_question = None

            if not headers:
                continue

        # Process each question on this page
        regions = get_question_regions(page, headers, page_height)

        for ri, (q_num, top_y, bottom_y) in enumerate(regions):
            log.info("Processing Q%d (page %d)", q_num, page_num + 1)

            # Skip the header bar itself (question number area)
            header_rect = headers[ri][0]
            text_start_y = header_rect.y1  # below the teal bar

            # Extract text lines for this question
            lines = extract_text_in_region(page, text_start_y, bottom_y, page_width)

            # Filter out the question number if it appears as first line
            if lines and lines[0].strip().isdigit():
                lines = lines[1:]

            # Parse question and options
            q_text, options = parse_question_from_lines(lines, style)

            # Build options list (fill gaps for missing options)
            max_idx = max((idx for idx, _ in options), default=-1)
            options_list = [""] * (max_idx + 1)
            for idx, text in options:
                if 0 <= idx < len(options_list):
                    if options_list[idx]:
                        options_list[idx] = clean_text(options_list[idx] + " " + text)
                    else:
                        options_list[idx] = text

            # Detect correct answer from yellow highlights
            answer_idx, hl_text = find_answer_for_question(
                page, yellow_highlights, top_y, bottom_y,
                list(enumerate(options_list)), style
            )

            # Check for associated image
            img_path = None
            img_bbox = find_image_for_question(image_bboxes, top_y, bottom_y)
            if img_bbox:
                img_path = extract_image_for_question(
                    page, doc, img_bbox, q_num, output_dir
                )

            q_data = {
                "id": q_num,
                "text": q_text,
                "options": options_list,
                "answer": answer_idx,
                "explanation": "",
            }
            if img_path:
                q_data["image"] = img_path

            # Track if this is the last question on the page and might continue
            if ri == len(regions) - 1:
                # Check if we have fewer than expected options (might continue on next page)
                if len(options_list) < 3 or (answer_idx == -1 and not hl_text):
                    # Likely continues on next page
                    pending_question = q_num
                    log.info("  Q%d may continue on next page", q_num)
                elif bottom_y >= page_height - 20:
                    # Question region extends to bottom of page
                    pending_question = q_num
                    log.info("  Q%d extends to page bottom, checking next page", q_num)

            questions.append(q_data)

            # Log option count and answer
            if answer_idx >= 0:
                log.info(
                    "  Q%d: %d options, answer=%d (%s)",
                    q_num,
                    len(options_list),
                    answer_idx,
                    options_list[answer_idx][:40] if answer_idx < len(options_list) else "?",
                )
            else:
                log.warning(
                    "  Q%d: %d options, NO ANSWER DETECTED (needs manual review)",
                    q_num,
                    len(options_list),
                )

    doc.close()

    return {
        "title": title_display,
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def write_json(data, output_path):
    """Write quiz data as JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Written: %s", output_path)


def write_js(data, output_path):
    """Write quiz data as a JS file with window.QUIZ_DATA wrapper."""
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by pdf2quiz.py\n")
        f.write("// Review answers marked as -1 (undetected) and fix manually\n")
        f.write(f"window.QUIZ_DATA = {json_str};\n")
    log.info("Written: %s", output_path)


def print_summary(data):
    """Print a summary of extracted quiz data."""
    questions = data["questions"]
    total = len(questions)
    detected = sum(1 for q in questions if q["answer"] >= 0)
    undetected = total - detected
    with_images = sum(1 for q in questions if q.get("image"))

    print()
    print("=" * 60)
    print(f"  Quiz: {data['title']}")
    print("=" * 60)
    print(f"  Total questions:    {total}")
    print(f"  Answers detected:   {detected}")
    if undetected:
        print(f"  NEEDS MANUAL REVIEW: {undetected}")
    print(f"  Questions w/ images: {with_images}")
    print("-" * 60)

    for q in questions:
        status = "OK" if q["answer"] >= 0 else "??"
        ans_display = ""
        if q["answer"] >= 0 and q["answer"] < len(q["options"]):
            ans_display = q["options"][q["answer"]][:35]
        elif q["answer"] == -1:
            ans_display = "UNDETECTED - needs manual review"

        print(
            f"  [{status}] Q{q['id']:>2d}: {q['text'][:45]:45s} -> {ans_display}"
        )

    if undetected:
        print()
        print("  NOTE: Questions marked [??] need manual review.")
        print("  Open the JSON file and set the correct 'answer' index (0-based).")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 pdf2quiz.py <path/to/quiz.pdf>")
        print()
        print("Converts a Georgian quiz PDF into JSON format for the quiz app.")
        print("The PDF should have teal header bars with question numbers")
        print("and yellow-highlighted correct answers.")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])

    if not pdf_path.exists():
        log.error("File not found: %s", pdf_path)
        sys.exit(1)

    if not pdf_path.suffix.lower() == ".pdf":
        log.warning("File does not have .pdf extension: %s", pdf_path)

    # Extract quiz data
    data = extract_quiz(pdf_path)

    # Output paths
    stem = pdf_path.stem
    # Remove .docx if present in the stem
    stem = re.sub(r"\.docx$", "", stem, flags=re.IGNORECASE)
    output_dir = pdf_path.parent
    json_path = output_dir / "data" / f"{stem}.json"
    js_path = output_dir / "data" / f"{stem}.js"

    # Ensure output directory exists
    json_path.parent.mkdir(parents=True, exist_ok=True)

    # Write outputs
    write_json(data, json_path)
    write_js(data, js_path)

    # Print summary
    print_summary(data)

    print(f"JSON: {json_path}")
    print(f"JS:   {js_path}")


if __name__ == "__main__":
    main()
