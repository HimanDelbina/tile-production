import re
import unicodedata
from decimal import Decimal
from typing import Optional, Tuple, Dict, Any, List

# Utility mappings for Persian/Arabic digit conversion
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

def normalize_text(text: str) -> str:
    """Standardize Persian/Arabic digits, letters, and whitespace."""
    if not isinstance(text, str):
        return ""
    # Translate Persian and Arabic digits
    text = text.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)
    # Unicode NFKC normalization
    text = unicodedata.normalize('NFKC', text)
    # Normalize Arabic letters to standard Persian
    text = text.replace('ي', 'ی').replace('ى', 'ی').replace('ك', 'ک')
    # Remove Tatweel (kashida)
    text = re.sub(r'[\u0640]', '', text)
    # Remove Arabic diacritics / vowels
    text = re.sub(r'[\u064b-\u065f]', '', text)
    # Standardize "نانوپولیش" to have standard spacing "نانو پولیش"
    text = re.sub(r'نانو\s*پولیش|نانوپولیش', 'نانو پولیش', text)
    # Collapse multiple whitespace, non-breaking spaces, and zero-width characters into single space
    text = re.sub(r'[\s\u200c\u200d\xa0]+', ' ', text)
    return text.strip()


# Regex for tile sizes (e.g. 60*120, 60x120, 60 × 120, 100*100)
# Lookbehind and lookahead prevent matching decimals (e.g. 2.16), thickness, or codes (e.g. 805)
SIZE_REGEX = re.compile(
    r'(?<![\d.])(?P<w>\d{2,4})\s*[*xX×]\s*(?P<h>\d{2,4})(?![\d.])',
    re.IGNORECASE
)

# Regex for Grade: matches درجه1, درجه 1, درجه6, درجهUNGRADE, ARTISTدرجهUNGRADE, etc.
GRADE_REGEX = re.compile(
    r'(?:درجه|grade)\s*[:#]?\s*(?P<code>ungrade|\d+|یک|دو|سه|چهار|پنج|شش)',
    re.IGNORECASE
)

# Regex for Piece Area (مساحت): e.g. مساحت 2.16, مساحت 2کارولین
PIECE_AREA_REGEX = re.compile(
    r'مساحت\s*[:#]?\s*(?P<area>\d+(?:\.\d+)?)',
    re.IGNORECASE
)

# Persian word-number mapping for grade words if written in letters
_WORD_TO_GRADE = {
    'یک': '1',
    'دو': '2',
    'سه': '3',
    'چهار': '4',
    'پنج': '5',
    'شش': '6',
}

def extract_size_spec(text: str) -> Tuple[Optional[Tuple[int, int]], Optional[str], Optional[str]]:
    """Extract tile size (width, length) without touching database.
    
    Returns:
        ((width, length), matched_string, error_message)
    """
    matches = list(SIZE_REGEX.finditer(text))
    if not matches:
        return None, None, "سایز در شرح کالا پیدا نشد."
    
    unique_sizes = {(int(m.group('w')), int(m.group('h'))) for m in matches}
    if len(unique_sizes) > 1:
        return None, None, "چند سایز متفاوت در شرح کالا یافت شد (ابهام در سایز)."
    
    w, h = next(iter(unique_sizes))
    first_match_str = matches[0].group(0)
    return (w, h), first_match_str, None


def extract_grade_spec(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract standardized grade code ('1', '2', '6', 'UNGRADE') without touching database.
    
    Returns:
        (grade_code, matched_string, error_message)
    """
    matches = list(GRADE_REGEX.finditer(text))
    found_codes = []
    first_match_str = None

    for m in matches:
        if first_match_str is None:
            first_match_str = m.group(0)
        raw_code = m.group('code').strip()
        if raw_code.upper() == 'UNGRADE':
            found_codes.append('UNGRADE')
        elif raw_code in _WORD_TO_GRADE:
            found_codes.append(_WORD_TO_GRADE[raw_code])
        else:
            found_codes.append(raw_code)
    
    # Fallback search for standalone ungrade / آنگرید
    if not found_codes:
        m_un = re.search(r'\b(?:آنگرید|ungrade)\b', text, re.IGNORECASE)
        if m_un:
            found_codes.append('UNGRADE')
            first_match_str = m_un.group(0)
            
    if not found_codes:
        return None, None, "درجه در شرح کالا پیدا نشد."
        
    unique_codes = list(dict.fromkeys(found_codes))
    if len(unique_codes) > 1:
        return None, None, "چند درجه متفاوت در شرح کالا یافت شد (ابهام در درجه)."
        
    return unique_codes[0], first_match_str, None


def extract_piece_area(text: str) -> Tuple[Optional[Decimal], Optional[str]]:
    """Extract piece area from description if present (e.g. مساحت 2.16 or مساحت 2)."""
    m = PIECE_AREA_REGEX.search(text)
    if not m:
        return None, None
    try:
        val = Decimal(m.group('area'))
        return val, m.group(0)
    except Exception:
        return None, None


def extract_technical_type_spec(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract explicit technical specifications only.
    
    Supported specifications:
    - پرسلان (or porcelain)
    - نانو پولیش (or پولیش)
    - Thickness: e.g. 10MIL, 12MIL
    
    Explicitly excludes:
    - Design names (صاحارا, لایت گری, کارولین, زئوس, etc.)
    - Area (مساحت)
    - Size (60*120, 100*100)
    - Grade (درجه 1, درجهUNGRADE, etc.)
    - Brand/code words (CH, ARTIST, مهتاب, YT 805, etc.)
    - Does NOT guess 'پرسلان' if absent in description.
    
    Returns:
        (canonical_technical_type_name, error_message)
    """
    parts = []
    
    # Check porcelain
    has_porcelain = bool(re.search(r'\b(?:پرسلان|porcelain)\b', text, re.IGNORECASE))
    if has_porcelain:
        parts.append('پرسلان')
        
    # Check treatment
    if 'نانو پولیش' in text:
        parts.append('نانو پولیش')
    elif re.search(r'\b(?:پولیش|polish)\b', text, re.IGNORECASE):
        parts.append('پولیش')
        
    # Check thickness (e.g. 10MIL, 12MIL)
    m_mil = re.search(r'\b(\d{1,2})\s*mil\b', text, re.IGNORECASE)
    if m_mil:
        parts.append(f"{m_mil.group(1)}MIL")
        
    if not parts:
        return None, None
        
    canonical_name = " ".join(parts)
    return canonical_name, None


def parse_description(raw: str) -> Dict[str, Any]:
    """Parse raw description and return pure extracted data without database access.
    
    Returns dictionary containing:
        - raw_description: original text
        - normalized_description: standardized text
        - size: (width, length) or None
        - size_match: matching substring
        - size_error: extraction error message if any
        - grade_code: '1', '2', '6', 'UNGRADE' or None
        - grade_match: matching substring
        - grade_error: extraction error message if any
        - technical_type_name: canonical name or None
        - piece_area: Decimal area per piece or None
        - cleaned_description: text with size, grade, and area tokens removed
        - errors: list of extraction error messages
        - warnings: list of extraction warnings
    """
    raw_str = str(raw or "")
    text = normalize_text(raw_str)
    
    size_spec, size_match, size_err = extract_size_spec(text)
    grade_code, grade_match, grade_err = extract_grade_spec(text)
    tech_name, tech_err = extract_technical_type_spec(text)
    piece_area, area_match = extract_piece_area(text)
    
    errors = []
    if size_err:
        errors.append(size_err)
    if grade_err:
        errors.append(grade_err)
    if tech_err:
        errors.append(tech_err)
        
    # Clean description for display
    cleaned = text
    if size_match:
        cleaned = cleaned.replace(size_match, "")
    if grade_match:
        cleaned = cleaned.replace(grade_match, "")
    if area_match:
        cleaned = cleaned.replace(area_match, "")
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return {
        "raw_description": raw_str,
        "normalized_description": text,
        "size": size_spec,
        "size_match": size_match,
        "size_error": size_err,
        "grade_code": grade_code,
        "grade_match": grade_match,
        "grade_error": grade_err,
        "technical_type_name": tech_name,
        "piece_area": piece_area,
        "cleaned_description": cleaned,
        "errors": errors,
        "warnings": [],
    }
