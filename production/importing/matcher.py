from decimal import Decimal
from typing import Optional, Dict, Any, List, Tuple
from ..models import Size, Grade, TechnicalType
from .parser import normalize_text

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

_TO_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

def match_size(width: Optional[int], length: Optional[int]) -> Tuple[Optional[Size], bool, Optional[str]]:
    """Match extracted width and length against database Size records.
    
    Tries exact (width, length), then reversed (length, width).
    
    Returns:
        (size_instance, is_reversed, message)
    """
    if not width or not length:
        return None, False, "سایز در شرح کالا پیدا نشد."
        
    # Try exact match first
    size = Size.objects.filter(width=width, length=length, active=True).first()
    if size:
        return size, False, None
        
    # Try reverse match
    size_rev = Size.objects.filter(width=length, length=width, active=True).first()
    if size_rev:
        return size_rev, True, f"تطبیق با سایز معکوس: {size_rev.width} × {size_rev.length}"
        
    size_display = f"{width}×{length}".translate(_TO_PERSIAN_DIGITS)
    # Check if an inactive size exists
    inactive = Size.objects.filter(width=width, length=length).first() or Size.objects.filter(width=length, length=width).first()
    if inactive and not inactive.active:
        return None, False, f"سایز {size_display} در سیستم غیرفعال است."
        
    return None, False, f"سایز {size_display} استخراج شد، اما در اطلاعات پایه تعریف نشده است."


def match_grade(grade_code: Optional[str]) -> Tuple[Optional[Grade], Optional[str]]:
    """Match extracted grade code ('1', '2', '6', 'UNGRADE') against database Grade records.
    
    Uses canonical grade name or explicit mapping. Never uses rank or ID as grade number!
    
    Returns:
        (grade_instance, message)
    """
    if not grade_code:
        return None, "درجه در شرح کالا پیدا نشد."
        
    code_upper = str(grade_code).strip().upper()
    
    if code_upper == 'UNGRADE':
        # Match "آنگرید" or "UNGRADE"
        grade = Grade.objects.filter(name__iexact='آنگرید', active=True).first()
        if not grade:
            grade = Grade.objects.filter(name__icontains='آنگرید', active=True).first()
        if not grade:
            grade = Grade.objects.filter(name__iexact='ungrade', active=True).first()
        if grade:
            return grade, None
        return None, "درجه آنگرید استخراج شد، اما گزینه متناظر تعریف نشده است."
        
    # If numeric grade code (e.g. '1', '2', '6')
    try:
        # Check all active grades and compare normalized names
        for g in Grade.objects.filter(active=True):
            norm_name = normalize_text(g.name).replace(" ", "")
            # Look for exact "درجه" + code e.g. "درجه1", "درجه2", "درجه6"
            if norm_name in (f"درجه{code_upper}", f"grade{code_upper}"):
                return g, None
    except Exception:
        pass
        
    code_display = code_upper.translate(_TO_PERSIAN_DIGITS)
    return None, f"درجه {code_display} استخراج شد، اما گزینه متناظر تعریف نشده است."


def match_technical_type(tech_name: Optional[str]) -> Tuple[Optional[TechnicalType], Optional[str]]:
    """Match extracted canonical technical type name against TechnicalType records.
    
    Returns:
        (technical_type_instance, message)
    """
    if not tech_name:
        return None, None
        
    # Search by exact name or normalized name
    tt = TechnicalType.objects.filter(name__iexact=tech_name).first()
    if tt:
        return tt, None
        
    norm_target = normalize_text(tech_name).replace(" ", "")
    for item in TechnicalType.objects.all():
        if normalize_text(item.name).replace(" ", "") == norm_target:
            return item, None
            
    return None, f"نوع فنی «{tech_name}» استخراج شد، اما در اطلاعات پایه تعریف نشده است."


from .validation import validate_import_row

def match_and_evaluate_row(
    parsed_data: Dict[str, Any],
    quantity: Optional[Decimal] = None,
    area: Optional[Decimal] = None,
    current_size: Optional[Size] = None,
    current_grade: Optional[Grade] = None,
    current_tech: Optional[TechnicalType] = None,
    user_edited_fields: Optional[Dict[str, Any]] = None,
    source_errors: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Combine extracted parsed data with database records and evaluate status using unified validation service.
    
    Preserves user overrides if provided.
    
    Returns evaluated row dictionary with matched objects, status, errors and warnings.
    """
    user_edited = user_edited_fields or {}
    
    # 1. Match or preserve Size
    is_reversed = False
    size_msg = None
    if 'size' in user_edited and user_edited['size']:
        if isinstance(user_edited['size'], Size):
            size_obj = user_edited['size']
        else:
            size_obj = Size.objects.filter(pk=user_edited['size'], active=True).first()
    elif current_size:
        size_obj = current_size
    else:
        w, l = parsed_data.get('size') if parsed_data.get('size') else (None, None)
        size_obj, is_reversed, size_msg = match_size(w, l)
        
    # 2. Match or preserve Grade
    grade_msg = None
    if 'grade' in user_edited and user_edited['grade']:
        if isinstance(user_edited['grade'], Grade):
            grade_obj = user_edited['grade']
        else:
            grade_obj = Grade.objects.filter(pk=user_edited['grade'], active=True).first()
    elif current_grade:
        grade_obj = current_grade
    else:
        grade_code = parsed_data.get('grade_code')
        grade_obj, grade_msg = match_grade(grade_code)
        
    # 3. Match or preserve TechnicalType
    tech_msg = None
    if 'technical_type' in user_edited:
        if isinstance(user_edited['technical_type'], TechnicalType):
            tech_obj = user_edited['technical_type']
        elif user_edited['technical_type']:
            tech_obj = TechnicalType.objects.filter(pk=user_edited['technical_type']).first()
        else:
            tech_obj = None
    elif current_tech:
        tech_obj = current_tech
    else:
        tech_name = parsed_data.get('technical_type_name')
        tech_obj, tech_msg = match_technical_type(tech_name)
        
    # 4. Area
    raw_area = user_edited.get('area') if 'area' in user_edited else area
    
    # Run unified validation service
    return validate_import_row(
        parsed_data=parsed_data,
        quantity=quantity,
        area=raw_area,
        size_obj=size_obj,
        grade_obj=grade_obj,
        tech_obj=tech_obj,
        source_errors=source_errors,
        is_reversed_size=is_reversed,
        size_msg=size_msg,
        grade_msg=grade_msg,
        tech_msg=tech_msg,
    )
