"""
Validates that a document (e.g. "Previous Employment Relieving Letter")
has actually been signed. Ported from Mohan's signature_check.py --
same three detection methods (any one match = signed): a text marker,
an embedded image over the signature box, or ink/pixel density in the
rendered box. Kept fully rule-based (no AI call needed for a yes/no
pixel check); only the reasoning line goes through Ollama with a
template fallback, for consistency with the other agents.
"""
import fitz  # PyMuPDF
from app.ai_client import call_ollama_json, OllamaError

LABEL = "Candidate Signature"
TEXT_MARKER = "digitally captured signature"

BOX_HEIGHT_ABOVE_LINE = 40
BOX_PADDING_BELOW_LABEL = 5
INK_PIXEL_THRESHOLD = 0.002

REASONING_PROMPT = """In one sentence, summarize this signature check for
an HR reviewer: label_found={label_found}, signed={signed} (text_marker=
{text_marker}, embedded_image={embedded_image}, ink_detected={ink_detected}).
Respond ONLY with JSON: {{"reasoning": "<one sentence>"}}
"""


def _find_signature_box(page):
    hits = page.search_for(LABEL)
    if not hits:
        return None
    label_rect = hits[0]
    return fitz.Rect(
        label_rect.x0,
        label_rect.y0 - BOX_HEIGHT_ABOVE_LINE - BOX_PADDING_BELOW_LABEL,
        label_rect.x1 + 150,
        label_rect.y0 - BOX_PADDING_BELOW_LABEL,
    )


def _has_text_marker(page, box) -> bool:
    return TEXT_MARKER in page.get_text("text", clip=box).lower()


def _has_embedded_image(page, box) -> bool:
    for img in page.get_image_info():
        if fitz.Rect(img["bbox"]).intersects(box):
            return True
    return False


def _has_ink(page, box) -> bool:
    zoom = 4
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=box)
    samples = pix.samples
    n = pix.n
    total_pixels = pix.width * pix.height
    if total_pixels == 0:
        return False
    non_white = 0
    for i in range(0, len(samples), n):
        if any(c < 245 for c in samples[i:i + 3]):
            non_white += 1
    return (non_white / total_pixels) > INK_PIXEL_THRESHOLD


def validate_signature(file_path: str) -> dict:
    doc = fitz.open(file_path)

    label_found = False
    text_flag = image_flag = ink_flag = False

    for page in doc:
        box = _find_signature_box(page)
        if box is None:
            continue
        label_found = True
        text_flag = text_flag or _has_text_marker(page, box)
        image_flag = image_flag or _has_embedded_image(page, box)
        ink_flag = ink_flag or _has_ink(page, box)

    doc.close()

    if not label_found:
        return {
            "status": "NEEDS_REVIEW",
            "signed": False,
            "reasoning": "No 'Candidate Signature' line was found in the document -- couldn't check for a signature automatically.",
        }

    signed = text_flag or image_flag or ink_flag
    overall_status = "PASS" if signed else "FAIL"

    try:
        result = call_ollama_json(REASONING_PROMPT.format(
            label_found=label_found, signed=signed, text_marker=text_flag,
            embedded_image=image_flag, ink_detected=ink_flag,
        ))
        reasoning = result.get("reasoning", "")
    except OllamaError:
        reasoning = f"Signature {'detected' if signed else 'not detected'} (text_marker={text_flag}, embedded_image={image_flag}, ink={ink_flag})."

    return {
        "status": overall_status,
        "signed": signed,
        "text_marker": text_flag,
        "embedded_image": image_flag,
        "ink_detected": ink_flag,
        "reasoning": reasoning,
    }
