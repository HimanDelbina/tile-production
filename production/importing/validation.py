import math
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, List, Tuple
from django.conf import settings
from django.core.exceptions import ValidationError
from ..models import Size, Grade, TechnicalType

MAX_UPLOAD_SIZE = getattr(settings, 'DJANGO_MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
MAX_IMPORT_ROWS = getattr(settings, 'DJANGO_MAX_IMPORT_ROWS', 2000)
MAX_DECIMAL_AREA = Decimal('999999999999.99')
MIN_DECIMAL_AREA = Decimal('0.01')


def validate_file_limits(file_obj) -> None:
    """Validate that uploaded file does not exceed size limits."""
    if hasattr(file_obj, 'size') and file_obj.size > MAX_UPLOAD_SIZE:
        max_mb = MAX_UPLOAD_SIZE / (1024 * 1024)
        raise ValidationError(f"حجم فایل بیش از حد مجاز است (حداکثر {max_mb:.1f} مگابایت).")


def validate_sheet_limits(sheet) -> None:
    """Validate row count to prevent denial-of-service / excessive memory consumption."""
    if sheet.max_row is not None and sheet.max_row > MAX_IMPORT_ROWS + 10:
        raise ValidationError(
            f"تعداد سطرهای فایل اکسل ({sheet.max_row}) بیش از سقف مجاز ({MAX_IMPORT_ROWS} ردیف) است. لطفاً فایل را به بخش‌های کوچک‌تر تقسیم کنید."
        )


def validate_import_row(
    parsed_data: Dict[str, Any],
    quantity: Optional[Decimal] = None,
    area: Optional[Decimal] = None,
    size_obj: Optional[Size] = None,
    grade_obj: Optional[Grade] = None,
    tech_obj: Optional[TechnicalType] = None,
    source_errors: Optional[List[Dict[str, str]]] = None,
    is_reversed_size: bool = False,
    size_msg: Optional[str] = None,
    grade_msg: Optional[str] = None,
    tech_msg: Optional[str] = None,
) -> Dict[str, Any]:
    """Unified validation service for an imported row.
    
    Used during:
    1. Initial file upload / parsing
    2. Reprocess
    3. Creating missing base data
    4. Saving manual row edits
    5. Final confirmation
    
    Returns standard dictionary with validation status, errors, and warnings.
    """
    errors: List[str] = []
    warnings: List[str] = list(parsed_data.get('warnings', []))
    active_source_errors: List[Dict[str, str]] = list(source_errors or [])

    # 1. Source file errors (formulas, corrupted reading, etc.)
    for s_err in active_source_errors:
        msg = s_err.get('message')
        if msg and msg not in errors:
            errors.append(msg)

    # 2. Validate Production Quantity
    clean_quantity = quantity
    if clean_quantity is not None:
        try:
            if isinstance(clean_quantity, float) and (math.isnan(clean_quantity) or math.isinf(clean_quantity)):
                errors.append("جمع تولید نامعتبر است (NaN یا Infinity).")
                clean_quantity = None
            else:
                dec_q = Decimal(str(clean_quantity))
                if dec_q < Decimal('0'):
                    errors.append("جمع تولید نمی‌تواند منفی باشد.")
                elif dec_q > MAX_DECIMAL_AREA:
                    errors.append("مقدار جمع تولید خارج از محدوده مجاز است.")
                clean_quantity = dec_q
        except (InvalidOperation, ValueError, TypeError):
            errors.append("جمع تولید عددی نامعتبر است.")
            clean_quantity = None

    # 3. Validate Area (متراژ)
    clean_area = None
    if area not in (None, ''):
        try:
            if isinstance(area, float) and (math.isnan(area) or math.isinf(area)):
                errors.append("متراژ نامعتبر است (NaN یا Infinity).")
            else:
                dec_area = Decimal(str(area))
                if dec_area < MIN_DECIMAL_AREA:
                    errors.append("متراژ باید بزرگ‌تر از صفر باشد.")
                elif dec_area > MAX_DECIMAL_AREA:
                    errors.append("متراژ خارج از سقف ظرفیت سیستم است.")
                else:
                    clean_area = dec_area.quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError, TypeError):
            errors.append("مقدار متراژ عددی معتبر نیست.")
    else:
        errors.append("متراژ الزامی است.")

    # 4. Validate Size
    if not size_obj:
        errors.append(size_msg or parsed_data.get('size_error') or "سایز تعیین نشده است.")
    elif not size_obj.active:
        errors.append(f"سایز {size_obj} غیرفعال است.")

    # 5. Validate Grade
    if not grade_obj:
        errors.append(grade_msg or parsed_data.get('grade_error') or "درجه تعیین نشده است.")
    elif not grade_obj.active:
        errors.append(f"درجه {grade_obj} غیرفعال است.")

    # 6. Validate Technical Type
    tech_name = parsed_data.get('technical_type_name')
    if tech_name and not tech_obj:
        errors.append(tech_msg or f"نوع فنی «{tech_name}» در اطلاعات پایه تعیین یا انتخاب نشده است.")

    # 7. Consistency Check: quantity * piece_area (ضریب مساحت واحد تولید) vs area
    piece_area = parsed_data.get('piece_area')
    if clean_quantity is not None and piece_area is not None and clean_area is not None:
        try:
            expected_area = (clean_quantity * piece_area).quantize(Decimal('0.01'))
            if abs(expected_area - clean_area) > Decimal('0.05'):
                warnings.append(
                    f"هشدار: حاصل‌ضرب جمع تولید ({clean_quantity}) در ضریب مساحت واحد تولید ({piece_area}) برابر {expected_area} است که با متراژ ردیف ({clean_area}) اختلاف دارد."
                )
        except Exception:
            pass

    # Deduplicate errors preserving order
    unique_errors = list(dict.fromkeys(errors))
    unique_warnings = list(dict.fromkeys(warnings))

    status = 'ok' if not unique_errors else 'error'
    all_messages = unique_errors + unique_warnings

    return {
        "is_ok": (status == 'ok'),
        "status": status,
        "errors": unique_errors,
        "warnings": unique_warnings,
        "error_message": "؛ ".join(all_messages),
        "area": clean_area if clean_area is not None else area,
        "quantity": clean_quantity,
        "size": size_obj,
        "is_reversed_size": is_reversed_size,
        "grade": grade_obj,
        "technical_type": tech_obj,
        "source_errors": active_source_errors,
    }
