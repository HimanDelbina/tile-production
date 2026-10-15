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


# Common ceramic tile dimension values in cm
COMMON_DIMS = {
    15, 20, 25, 30, 33, 40, 45, 50, 60, 70, 75, 80, 90, 100, 120,
    140, 150, 160, 180, 240, 260, 278, 280, 300, 320
}

# Regex for tile sizes (e.g. 60*120, 60x120, 60 × 120, 100*100, 60-120, 60/120, 60 در 120)
# Lookbehind and lookahead prevent matching decimals (e.g. 2.16), thickness, or codes (e.g. 805)
SIZE_REGEX = re.compile(
    r'(?<![\d.])(?P<w>\d{2,3})\s*(?:[*xX×/\\]|\s+در\s+|\-)\s*(?P<h>\d{2,3})(?![\d.])',
    re.IGNORECASE
)

def parse_concat_size(token: str) -> Optional[Tuple[int, int]]:
    """Parse concatenated dimensions like 60120, 40120, 100100, 6060, 8080."""
    if not (4 <= len(token) <= 6) or not token.isdigit():
        return None
    for split_idx in (2, 3):
        w_str = token[:split_idx]
        h_str = token[split_idx:]
        if w_str.isdigit() and h_str.isdigit():
            w, h = int(w_str), int(h_str)
            if w in COMMON_DIMS and h in COMMON_DIMS:
                return (w, h)
    return None

def extract_size_spec(text: str) -> Tuple[Optional[Tuple[int, int]], Optional[str], Optional[str]]:
    """Extract tile size (width, length) without touching database.
    
    Supports:
        - Delimited sizes: 60*120, 60x120, 60 × 120, 60-120, 60/120, 60 در 120
        - Concatenated sizes: 60120, 40120, 100100, 6060, 8080, etc.
        - Prefixed with سایز / ابعاد (e.g. سایز 60120)
    
    Returns:
        ((width, length), matched_string, error_message)
    """
    matches = list(SIZE_REGEX.finditer(text))
    if matches:
        unique_sizes = {(int(m.group('w')), int(m.group('h'))) for m in matches}
        if len(unique_sizes) > 1:
            return None, None, "چند سایز متفاوت در شرح کالا یافت شد (ابهام در سایز)."
        w, h = next(iter(unique_sizes))
        first_match_str = matches[0].group(0)
        return (w, h), first_match_str, None

    # Fallback to concatenated numbers (e.g. 60120, 40120, 100100, سایز 60120)
    concat_matches = []
    for m in re.finditer(r'(?:(?:سایز|ابعاد)\s*[:#]?\s*)?(?<![\d.])(?P<num>\d{4,6})(?![\d.])', text):
        res = parse_concat_size(m.group('num'))
        if res:
            concat_matches.append((res, m.group(0)))

    if concat_matches:
        unique_concat = list(dict.fromkeys(s for s, _ in concat_matches))
        if len(unique_concat) > 1:
            return None, None, "چند سایز متفاوت در شرح کالا یافت شد (ابهام در سایز)."
        return concat_matches[0][0], concat_matches[0][1], None

    return None, None, "سایز در شرح کالا پیدا نشد."


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
    """Extract piece area from description if present (e.g. مساحت 2.16 or مساحت 2 or (2.4))."""
    m = PIECE_AREA_REGEX.search(text)
    if m:
        try:
            val = Decimal(m.group('area'))
            return val, m.group(0)
        except Exception:
            pass

    # Fallback: parenthesized area e.g. (2.4), (1.44), (2.16)
    m_paren = re.search(r'\(\s*(?P<area>\d+(?:\.\d+)?)\s*\)', text)
    if m_paren:
        try:
            val = Decimal(m_paren.group('area'))
            if Decimal('0.1') <= val <= Decimal('20.0'):
                return val, m_paren.group(0)
        except Exception:
            pass

    return None, None


# Regex for tile thickness (ضخامت): e.g. 10MIL, 12MIL, 10 mil, 10میل, 10 میلیمتر, ضخامت 10
THICKNESS_REGEX = re.compile(
    r'(?:\bضخامت\s*[:#]?\s*(?P<th1>\d{1,2}(?:\.\d+)?)\s*(?:mil|میل|میلی\s*متر|میلیمتر|mm)?\b)|'
    r'(?:\b(?P<th2>\d{1,2}(?:\.\d+)?)\s*(?:mil|میل|میلی\s*متر|میلیمتر|mm)\b)',
    re.IGNORECASE
)

# Regex patterns for Glaze types (پولیش، مات، براق)
GLAZE_POLISH_REGEX = re.compile(r'\b(?:نانو\s*پولیش|سوپر\s*پولیش|پولیش|polish)\b', re.IGNORECASE)
GLAZE_MATTE_REGEX = re.compile(r'\b(?:نیمه\s*مات|مات|matte)\b', re.IGNORECASE)
GLAZE_GLOSSY_REGEX = re.compile(r'\b(?:سوپر\s*براق|براق|glossy)\b', re.IGNORECASE)
GLAZE_SUGAR_REGEX = re.compile(r'\b(?:شوگر|sugar)\b', re.IGNORECASE)

def extract_glaze_spec(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract tile glaze (لعاب: پولیش, مات, براق, etc.) without touching database.
    
    Returns:
        (canonical_glaze_name, matched_string, error_message)
    """
    matches = []
    m = GLAZE_POLISH_REGEX.search(text)
    if m:
        matches.append(('پولیش', m.group(0)))
    m = GLAZE_MATTE_REGEX.search(text)
    if m:
        matches.append(('مات', m.group(0)))
    m = GLAZE_GLOSSY_REGEX.search(text)
    if m:
        matches.append(('براق', m.group(0)))
    m = GLAZE_SUGAR_REGEX.search(text)
    if m:
        matches.append(('شوگر', m.group(0)))

    if not matches:
        return None, None, None

    unique_names = list(dict.fromkeys(n for n, _ in matches))
    if len(unique_names) > 1:
        return None, None, "چند نوع لعاب متفاوت در شرح کالا یافت شد (ابهام در لعاب)."

    name, match_str = matches[0]
    return name, match_str, None


def extract_technical_type_spec(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract tile thickness (ضخامت) as technical specification.
    
    Returns:
        (canonical_thickness_name, error_message)
    """
    m = THICKNESS_REGEX.search(text)
    if not m:
        return None, None
    val = m.group('th1') or m.group('th2')
    canonical_name = f"{val}MIL"
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
        - technical_type_name: canonical thickness (e.g. 10MIL) or None
        - glaze_name: canonical glaze ('پولیش', 'مات', 'براق') or None
        - glaze_match: matching substring
        - glaze_error: extraction error message if any
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
    glaze_name, glaze_match, glaze_err = extract_glaze_spec(text)
    piece_area, area_match = extract_piece_area(text)
    
    errors = []
    if size_err:
        errors.append(size_err)
    if grade_err:
        errors.append(grade_err)
    if tech_err:
        errors.append(tech_err)
    if glaze_err:
        errors.append(glaze_err)
        
    # Clean description for display
    cleaned = text
    if size_match:
        cleaned = cleaned.replace(size_match, "")
    if grade_match:
        cleaned = cleaned.replace(grade_match, "")
    if glaze_match:
        cleaned = cleaned.replace(glaze_match, "")
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
        "glaze_name": glaze_name,
        "glaze_match": glaze_match,
        "glaze_error": glaze_err,
        "piece_area": piece_area,
        "cleaned_description": cleaned,
        "errors": errors,
        "warnings": [],
    }
