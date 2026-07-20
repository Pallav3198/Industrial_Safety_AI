"""
services/layout_extraction.py
--------------------------------
Auto-detects the facility layout / floor plan page inside a facility's
uploaded onboarding PDF, renders it as an image, and locates the boxes
and text labels on it -- so the Facility Layout editor (Step 4) starts
from a real, pre-populated drawing instead of a blank canvas the user
has to build by hand.

Pipeline:

  1. find_layout_page()        -- scores every PDF page on several
                                   cheap, local signals and ranks pages
                                   best-first (see _score_page()).
  2. confirm_layout_page_multi() -- shows Gemini the top few candidates
                                   *together in one call* and asks it to
                                   pick the real layout page (or none).
                                   Always "no confident match" in mock
                                   mode (Config.USE_MOCK_AI) -- the
                                   top-ranked heuristic candidate is
                                   used as-is, flagged low-confidence,
                                   so the pipeline still works with no
                                   API key, same convention as
                                   services/ai_extraction.py.
  3. _extract_page_as_png()    -- renders the winning page at a higher
                                   (but capped) zoom for a crisp editing
                                   image.
  4. _contour_box_detect()     -- OpenCV contour detection for
                                   rectangle/box-like shapes on that image.
  5. _ocr_text_boxes()         -- EasyOCR over the whole image once (not
                                   per box -- see its docstring).
  6. _associate_text_to_boxes() -- matches each OCR text run to the
                                   detection box it falls inside.

detect_facility_layout() ties 1-2-3-4-5-6 together for automatic
detection. detect_facility_layout_for_page() runs just 3-4-5-6 against a
page the user picked by hand -- the manual override for when automatic
detection picks the wrong page (see routes/factory_routes.py's
/layout/detect_page).

All heavy dependencies (PyMuPDF/fitz, opencv-python, easyocr, Pillow)
are imported lazily inside the functions that need them, not at module
import time, so the rest of the app still boots normally even before
they're installed. Routes calling into this module catch
ImportError/Exception and report a friendly error instead of crashing
(same fail-gracefully approach services/ai_extraction.py uses).

ACCURACY NOTES -- why the old scoring missed real layout pages, and
what changed:

  * A layout page pasted in as a raster image (very common -- it's a
    scanned/exported drawing, not native PDF vector content) has *no*
    extractable text at all, so it used to get zero credit from the
    keyword and dimension-number signals, and had to win on box_count
    alone. `_textless_drawing_signal` now explicitly rewards "lots of
    box-like contours, almost no extractable text" as its own positive
    signal, since that combination is a strong, generic indicator of
    "this is a pasted-in drawing," not an accident of one document.
  * The keyword list included the bare word "drawing", which matches
    the title block of *any* engineering drawing (P&IDs, single-line
    diagrams, elevations) -- not just the layout. Replaced with more
    specific standard industry terms (site plan, plot plan, general
    arrangement/GA drawing, block/equipment layout), and added an
    explicit negative-keyword penalty for pages that look like a
    different drawing type entirely.
  * The dimension-number regex (`\\d{4,5}`) matched far more than actual
    drawing dimensions -- phone number segments ("+91-98480-21001"),
    years in dates ("12-Jul-2026"), reference codes
    ("APPCB/CFO/VSP/2024/00417") are all 4-5 digit runs. A table-heavy
    page (e.g. an Employee Directory full of phone numbers) could rack
    up a higher "dimension number" score than the real drawing. The
    regex now excludes digit runs immediately adjacent to a hyphen,
    slash, plus sign, or another digit/dot -- the pattern real drawing
    dimensions follow (bare numbers near dimension lines) but phone
    numbers, codes, and dates don't.
  * Large, few boxes (rooms/buildings) vs. many small boxes (P&ID
    symbols, table cells) is itself a useful generic signal --
    `_contour_box_signal()` now returns a separate "large box" count
    (contours covering a meaningful fraction of the page) in addition
    to the total, and large boxes are weighted more heavily.
  * Confirmation used to ask Gemini "is this ONE page a layout, yes or
    no?" against the top 2 candidates independently, and silently used
    the top-ranked page anyway if both said no -- no path to recovery
    from a bad heuristic ranking. confirm_layout_page_multi() now shows
    the top few candidates *together* in a single call so the model can
    compare them directly (the way a person would), and the result is
    honestly flagged low-confidence rather than silently trusted when
    nothing is confirmed.
  * detect_facility_layout_for_page() + the /layout/detect_page route +
    the "wrong page? enter the page number" UI control are the actual
    fail-safe: no scoring heuristic will be right 100% of the time, so
    correcting the page number directly is always available and cheap
    (it skips scoring/confirmation entirely).

PERFORMANCE NOTES:

  * EasyOCR's model load (PyTorch under the hood) is a one-time,
    10s-to-a-couple-minutes cost the first time _get_ocr_reader() runs
    in a process. warmup_ocr_async(), called from app.py on startup,
    kicks this off in a background thread as soon as the server starts.
  * find_layout_page() opens the PDF once and reuses that fitz.Document
    across every page's score, instead of re-opening/re-parsing the
    whole file from disk once per page.
  * Nothing used to cap the rendered image resolution -- large-format
    sheets (A1/A0) at a fixed zoom could render to huge images, and
    both contour analysis and (especially) EasyOCR scale with pixel
    count. _capped_zoom() now bounds every render in this pipeline to a
    target pixel count (small for the scoring pass, larger for the
    final detection/OCR image).
  * _score_page() now skips rendering + contour detection entirely for
    pages that are obviously dense body text with no layout-keyword hit
    (a cheap, render-free text check first) -- on a typical multi-page
    onboarding PDF, most pages are narrative/table sections that could
    never win anyway, and this avoids paying for an image render and
    OpenCV contour pass on each of them.
  * confirm_layout_page_multi() replaced up to two separate Gemini
    calls with one, which also means one network round trip instead of
    up to two.
"""

import os
import re
import threading
import uuid

from config import Config

# --- Keyword signals -------------------------------------------------------

# Specific, standard industry terms for this drawing type -- deliberately
# NOT including the bare word "drawing", which matches the title block of
# any engineering drawing (P&ID, single-line diagram, elevation), not just
# a site/facility layout.
LAYOUT_KEYWORDS = re.compile(
    r"\b(layout|floor\s*plan|facility\s*layout|site\s*plan|plot\s*plan|"
    r"general\s*arrangement|g\.?a\.?\s*drawing|block\s*layout|equipment\s*layout)\b",
    re.IGNORECASE,
)

# Other common drawing types that should NOT be picked as the facility
# layout, even though they also have lots of boxes/dimensions.
NON_LAYOUT_KEYWORDS = re.compile(
    r"\b(p\s*&\s*id|piping\s*and\s*instrumentation|single\s*line\s*diagram|"
    r"process\s*flow\s*diagram|electrical\s*schematic|elevation|section\s*view)\b",
    re.IGNORECASE,
)

# Matches bare 4-5 digit numbers (real drawing dimensions, e.g. "18611",
# "6937") while excluding digit runs that are part of a larger token --
# phone number segments, dates, reference codes, alarm thresholds
# ("<5.0", ">17000"), and times are all 4-5 digit runs too, but are
# always adjacent to a hyphen, slash, plus/comparison sign, colon, comma,
# or another digit/dot -- which a standalone drawing dimension is not.
DIMENSION_NUMBER_RE = re.compile(r"(?<![\d\-+/.><:,])\b\d{4,5}\b(?![\d\-+/.><:,])")

_ocr_reader = None       # lazy singleton -- EasyOCR's model load is expensive, do it once per process
_warmup_started = False  # guards warmup_ocr_async() so repeated create_app() calls don't stack threads


# ===========================================================================
# Step 1-2: find and confirm the layout page
# ===========================================================================

def _capped_zoom(page, requested_zoom, max_dim):
    """Returns a zoom factor <= requested_zoom such that the rendered
    image's longer side doesn't exceed max_dim pixels. Large-format
    sheets (A1/A0 engineering drawings) can otherwise render to
    enormous images at a fixed zoom -- this is the single biggest lever
    on detection speed, since contour analysis and EasyOCR inference
    both scale with pixel count."""
    page_w, page_h = page.rect.width, page.rect.height  # in points, 1 point = 1/72 inch
    longer_side_at_zoom1 = max(page_w, page_h)
    if longer_side_at_zoom1 <= 0:
        return requested_zoom
    max_allowed_zoom = max_dim / longer_side_at_zoom1
    return min(requested_zoom, max_allowed_zoom)


def _render_page_to_array(doc, page_num, zoom=2.0, max_dim=None):
    """Renders one page of an already-open fitz.Document to a BGR numpy
    array. Doesn't open or close `doc` -- the caller owns its lifecycle,
    so a multi-page scan (find_layout_page) can open the PDF once and
    reuse it across every page instead of re-parsing the whole file
    from disk once per page."""
    import fitz  # PyMuPDF
    import cv2
    import numpy as np

    page = doc[page_num]
    effective_zoom = _capped_zoom(page, zoom, max_dim) if max_dim else zoom
    mat = fitz.Matrix(effective_zoom, effective_zoom)
    pix = page.get_pixmap(matrix=mat)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    return img, page


def _contour_box_signal(img):
    """Returns (total_box_count, large_box_count). A real facility
    layout typically has a small number of LARGE rectangular regions
    (rooms/buildings, each a meaningful fraction of the page) -- a P&ID
    or electrical schematic is the opposite: many small symbol-sized
    boxes. Tracking large boxes separately lets the scorer reward that
    shape difference, not just raw box density."""
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    h, w = img.shape[:2]
    page_area = w * h
    total = 0
    large = 0
    for c in contours:
        area = cv2.contourArea(c)
        if area < 25 or area > page_area * 0.9:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.03 * peri, True)
        if 4 <= len(approx) <= 6:
            total += 1
            if area > page_area * 0.01:
                large += 1
    return total, large


# The scoring pass only needs relative box-density/text signals, not a
# crisp image -- capping it small (long side <= 1000px) is a large
# speedup across a multi-page PDF with effectively no change in which
# page wins, since the score is a coarse heuristic either way.
_SCORE_ZOOM = 1.0
_SCORE_MAX_DIM = 1000

# A page with more body text than this, and no layout-keyword hit, is
# essentially certainly not the drawing page -- skip the expensive
# render + contour-detection step for it entirely (a pure text check,
# no rendering needed, so this is nearly free).
_SKIP_RENDER_WORD_COUNT = 250


def _score_page(doc, page_num):
    page = doc[page_num]
    text = page.get_text()
    word_count = len(text.split())
    keyword_hit = bool(LAYOUT_KEYWORDS.search(text))           # signal: header/title text
    non_layout_hit = bool(NON_LAYOUT_KEYWORDS.search(text))    # signal: looks like a different drawing type
    dim_numbers = len(DIMENSION_NUMBER_RE.findall(text))       # signal: dimension-like numbers (6937, 18611...)

    if word_count > _SKIP_RENDER_WORD_COUNT and not keyword_hit:
        box_count, large_box_count, textless_drawing = 0, 0, False
    else:
        img, _ = _render_page_to_array(doc, page_num, zoom=_SCORE_ZOOM, max_dim=_SCORE_MAX_DIM)
        box_count, large_box_count = _contour_box_signal(img)
        # Strong signal for a pasted-in/scanned drawing with no text
        # layer at all: lots of box-like contours, almost no text.
        textless_drawing = word_count < 15 and box_count >= 8

    score = 0
    score += min(box_count / 50, 5) * 2         # cap contribution, avoid runaway on huge drawings
    score += min(large_box_count, 6) * 1.5      # a handful of large regions strongly suggests rooms/buildings
    score += 5 if keyword_hit else 0
    score -= 4 if non_layout_hit else 0
    score += 4 if textless_drawing else 0
    score += min(dim_numbers, 10) * 0.5
    score -= min(word_count / 100, 5)           # penalize heavily-worded (text) pages

    return {
        "page": page_num, "score": round(score, 2), "box_count": box_count,
        "large_box_count": large_box_count, "word_count": word_count,
        "keyword_hit": keyword_hit, "non_layout_hit": non_layout_hit,
        "textless_drawing": textless_drawing, "dim_numbers": dim_numbers,
    }


def find_layout_page(pdf_path):
    """Returns every page's score dict, best candidate first. Opens the
    PDF once and reuses it across every page (see _render_page_to_array's
    docstring) instead of re-parsing the whole file from disk per page."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        scores = [_score_page(doc, i) for i in range(len(doc))]
    finally:
        doc.close()
    scores.sort(key=lambda s: s["score"], reverse=True)
    return scores


def get_pdf_page_count(pdf_path):
    """Fast page-count lookup (no rendering) -- used to validate a
    user-entered manual page number in the "wrong page? enter the page
    number" override control."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


# Gemini doesn't need a huge image either -- capping this also shrinks
# the upload payload, so the vision call itself comes back faster too.
_CONFIRM_ZOOM = 1.2
_CONFIRM_MAX_DIM = 900

# How many of the top heuristically-ranked pages to actually show Gemini
# for confirmation. More than a handful adds little (a bad heuristic
# ranking rarely puts the real page 6th+) while making the single
# confirmation call slower and more expensive.
_CONFIRM_SHORTLIST_SIZE = 5


def confirm_layout_page_multi(pdf_path, candidate_pages):
    """Shows Gemini all of `candidate_pages` (0-indexed page numbers)
    together in a single call and asks it to pick the one that's really
    a facility/site layout drawing. Returns the winning page number, or
    None if it picked none of them (or the response couldn't be parsed).

    This replaces asking about each candidate in isolation with one
    yes/no call per page: comparing candidates side by side (like a
    person flipping through pages would) is both more accurate and
    cheaper (one round trip instead of up to N)."""
    import fitz
    import cv2
    from google import genai
    from google.genai.types import Part

    doc = fitz.open(pdf_path)
    try:
        thumbnails = []
        for page_num in candidate_pages:
            img, _ = _render_page_to_array(doc, page_num, zoom=_CONFIRM_ZOOM, max_dim=_CONFIRM_MAX_DIM)
            _, buf = cv2.imencode(".png", img)
            thumbnails.append(buf.tobytes())
    finally:
        doc.close()

    contents = [
        "Each image below is a candidate page from a facility onboarding document, "
        "labeled Candidate 1, Candidate 2, and so on in that order. Which candidate, "
        "if any, shows a facility/factory floor plan or site layout drawing (rooms, "
        "equipment placement, and dimension lines)? Reply with just the candidate "
        "number (e.g. \"2\"), or NONE if none of them qualify."
    ]
    for i, image_bytes in enumerate(thumbnails, start=1):
        contents.append(f"Candidate {i}:")
        contents.append(Part.from_bytes(data=image_bytes, mime_type="image/png"))

    client = genai.Client(api_key=Config.GEMINI_API_KEY)
    response = client.models.generate_content(model=Config.GEMINI_MODEL, contents=contents)
    reply = response.text.strip()

    match = re.search(r"\d+", reply)
    if not match:
        return None
    choice = int(match.group())
    if 1 <= choice <= len(candidate_pages):
        return candidate_pages[choice - 1]
    return None


# ===========================================================================
# Step 3: render the winning page as an editing-quality PNG
# ===========================================================================

# This is the image both the user sees AND the one OCR/contour detection
# run against -- 3000px on the long side is still sharp enough to read
# and edit comfortably, while keeping OCR inference bounded even on a
# large-format sheet.
_EXTRACT_ZOOM = 3.0
_EXTRACT_MAX_DIM = 3000


def _extract_page_as_png(pdf_path, page_num, out_path, zoom=_EXTRACT_ZOOM, max_dim=_EXTRACT_MAX_DIM):
    import fitz
    import cv2

    doc = fitz.open(pdf_path)
    try:
        img, page = _render_page_to_array(doc, page_num, zoom=zoom, max_dim=max_dim)
    finally:
        doc.close()
    cv2.imwrite(out_path, img)
    return out_path


# ===========================================================================
# Step 4-6: detect boxes, OCR text, associate the two
# ===========================================================================

def _contour_box_detect(image_bytes, min_area=25, max_area_frac=0.9, approx_eps=0.03):
    import cv2
    import numpy as np

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    h, w = img.shape[:2]

    boxes = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > w * h * max_area_frac:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, approx_eps * peri, True)
        if 4 <= len(approx) <= 6:
            x, y, bw, bh = cv2.boundingRect(c)
            boxes.append({
                "id": f"box_{uuid.uuid4().hex[:8]}", "x": int(x), "y": int(y),
                "width": int(bw), "height": int(bh), "text": "",
            })
    return boxes


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["en"], gpu=False)
    return _ocr_reader


def warmup_ocr_async():
    """Best-effort: starts loading the EasyOCR model in a background
    thread as soon as the app starts (called once from app.py), so it's
    (usually) already warm by the time a real user clicks "Detect
    Layout from PDF" -- instead of that click paying EasyOCR's one-time
    model-load cost (10s to a couple of minutes, worst on the very
    first run while it downloads model weights).

    Safe to call more than once -- only the first call actually starts
    a thread (guards against e.g. the test suite creating many app
    instances via create_app()). Never raises: if easyocr isn't
    installed yet, or loading fails for any reason, this silently no-
    ops -- it's a startup nicety, not something that should ever delay
    or break app startup. The next real detection request will then
    just load the model itself, the same as before this existed.
    """
    global _warmup_started
    if _warmup_started:
        return
    _warmup_started = True

    def _load():
        try:
            _get_ocr_reader()
            print("[layout_extraction] EasyOCR model warmed up.")
        except Exception as exc:  # noqa: BLE001 -- best-effort warmup, never fatal
            print(f"[layout_extraction] EasyOCR warmup skipped ({exc}); "
                  f"it'll load on the first real detection request instead.")

    threading.Thread(target=_load, daemon=True, name="easyocr-warmup").start()


def _ocr_text_boxes(image_bytes):
    """Runs OCR once over the whole image, returns text boxes independent
    of the detection boxes. Cheaper and more reliable than cropping and
    re-running OCR per box (text spanning a box edge won't get cut off)."""
    from io import BytesIO
    from PIL import Image

    reader = _get_ocr_reader()
    img = _np_array_rgb(Image.open(BytesIO(image_bytes)).convert("RGB"))
    results = reader.readtext(img)
    out = []
    for bbox, text, conf in results:
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        out.append({
            "x": min(xs), "y": min(ys),
            "width": max(xs) - min(xs), "height": max(ys) - min(ys),
            "cx": (min(xs) + max(xs)) / 2, "cy": (min(ys) + max(ys)) / 2,
            "text": text, "conf": float(conf),
        })
    return out


def _np_array_rgb(pil_image):
    import numpy as np
    return np.array(pil_image)


def _associate_text_to_boxes(detections, ocr_boxes, max_distance=40):
    """For each detection box, find OCR text whose center falls inside
    it. If nothing falls inside (common for room labels sitting just
    above/beside the box rather than strictly within it), fall back to
    the nearest text center within max_distance pixels."""
    result = []
    used_ocr_idx = set()

    for det in detections:
        dx1, dy1 = det["x"], det["y"]
        dx2, dy2 = det["x"] + det["width"], det["y"] + det["height"]

        matched_texts = []
        for i, ocr in enumerate(ocr_boxes):
            if dx1 <= ocr["cx"] <= dx2 and dy1 <= ocr["cy"] <= dy2:
                matched_texts.append(ocr["text"])
                used_ocr_idx.add(i)

        if not matched_texts:
            box_cx, box_cy = (dx1 + dx2) / 2, (dy1 + dy2) / 2
            best_i, best_dist = None, max_distance
            for i, ocr in enumerate(ocr_boxes):
                if i in used_ocr_idx:
                    continue
                dist = ((ocr["cx"] - box_cx) ** 2 + (ocr["cy"] - box_cy) ** 2) ** 0.5
                if dist < best_dist:
                    best_i, best_dist = i, dist
            if best_i is not None:
                matched_texts.append(ocr_boxes[best_i]["text"])

        new_det = dict(det)
        new_det["text"] = " ".join(matched_texts)
        result.append(new_det)
    return result


def _detect_on_page(pdf_path, save_dir, factory_id, page_num):
    """Shared tail end of the pipeline (steps 3-6): render the given
    0-indexed page, detect boxes, OCR, associate. Used by both automatic
    detection and the manual page-override path."""
    from PIL import Image

    os.makedirs(save_dir, exist_ok=True)
    image_filename = f"{factory_id}_layout.png"
    out_path = os.path.join(save_dir, image_filename)
    _extract_page_as_png(pdf_path, page_num, out_path)

    with open(out_path, "rb") as f:
        image_bytes = f.read()

    detections = _contour_box_detect(image_bytes)
    ocr_boxes = _ocr_text_boxes(image_bytes)
    labeled_detections = _associate_text_to_boxes(detections, ocr_boxes)

    with Image.open(out_path) as img:
        width, height = img.width, img.height

    return {
        "image_filename": image_filename,
        "source_page": page_num,
        "canvas": {"width": width, "height": height},
        "shapes": labeled_detections,
    }


# ===========================================================================
# Entry points
# ===========================================================================

def detect_facility_layout(pdf_path, save_dir, factory_id):
    """
    Main entry point for AUTOMATIC detection, called by
    POST /factory/<id>/layout/detect.

    Runs the whole pipeline against `pdf_path` and saves the rendered
    layout page as a PNG into `save_dir` (Config.UPLOAD_FOLDER -- already
    served at /static/uploads/<filename>, so no separate file-serving
    route is needed).

    Returns:
        {
            "image_filename": str,
            "source_page": int,             # 0-indexed PDF page number
            "canvas": {"width": int, "height": int},
            "shapes": [{"id", "x", "y", "width", "height", "text"}, ...],
            "confidence": "confirmed" | "low",
            "confidence_note": str,          # human-readable explanation, shown in the UI
            "total_pages": int,
        }

    Raises on failure (missing PDF, no pages to scan, a missing optional
    dependency, etc.) -- the caller is responsible for catching that and
    turning it into a user-facing error, same as
    services/ai_extraction.py does for its Gemini call.
    """
    candidates = find_layout_page(pdf_path)
    if not candidates:
        raise RuntimeError("The uploaded PDF has no pages to scan for a layout drawing.")

    shortlist = candidates[:_CONFIRM_SHORTLIST_SIZE]

    if Config.USE_MOCK_AI:
        layout_page_num = shortlist[0]["page"]
        confidence = "low"
        confidence_note = "No GEMINI_API_KEY configured -- picked using local heuristics only, not vision-confirmed. Please check the result, or enter the correct page number below."
    else:
        try:
            winner = confirm_layout_page_multi(pdf_path, [c["page"] for c in shortlist])
        except Exception as exc:  # noqa: BLE001 -- a flaky vision call shouldn't block detection
            print(f"[layout_extraction] confirm_layout_page_multi failed, treating as unconfirmed: {exc}")
            winner = None

        if winner is not None:
            layout_page_num = winner
            confidence = "confirmed"
            confidence_note = ""
        else:
            layout_page_num = shortlist[0]["page"]
            confidence = "low"
            confidence_note = "Couldn't confidently confirm a layout page -- showing the best guess. Please check the result, or enter the correct page number below."

    result = _detect_on_page(pdf_path, save_dir, factory_id, layout_page_num)
    result["confidence"] = confidence
    result["confidence_note"] = confidence_note
    result["total_pages"] = len(candidates)
    return result


def detect_facility_layout_for_page(pdf_path, save_dir, factory_id, page_num):
    """
    Manual-override entry point, called by
    POST /factory/<id>/layout/detect_page.

    Skips scoring and confirmation entirely and runs detection directly
    against `page_num` (0-indexed) -- the fail-safe for when automatic
    detection (detect_facility_layout above) picks the wrong page: no
    heuristic will be right 100% of the time, so being able to just say
    "actually, use page 19" is always available and is also much faster
    than a full auto-detect, since it skips scanning every page.

    Returns the same shape as detect_facility_layout(), with
    confidence="manual".
    """
    result = _detect_on_page(pdf_path, save_dir, factory_id, page_num)
    result["confidence"] = "manual"
    result["confidence_note"] = ""
    result["total_pages"] = get_pdf_page_count(pdf_path)
    return result