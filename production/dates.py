import re
from datetime import timedelta
import jdatetime
from django.utils import timezone
from django.core.exceptions import ValidationError
DIGITS=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫','01234567890123456789.')
def normalize(value): return str(value).translate(DIGITS).strip()
def parse_jalali(value):
    text=normalize(value)
    if not re.fullmatch(r'\d{4}/\d{1,2}/\d{1,2}',text): raise ValidationError('تاریخ شمسی را مانند ۱۴۰۵/۰۶/۱۸ وارد کنید.')
    try: return jdatetime.date(*map(int,text.split('/'))).togregorian()
    except (ValueError,OverflowError): raise ValidationError('این تاریخ شمسی معتبر نیست.')
def jalali(value):
    if not value: return ''
    return jdatetime.date.fromgregorian(date=value).strftime('%Y/%m/%d')
def period(preset,today=None):
    today=today or timezone.localdate()
    j=jdatetime.date.fromgregorian(date=today)
    if preset=='today': return today,today
    if preset=='yesterday': return today-timedelta(days=1),today-timedelta(days=1)
    if preset=='week': return today-timedelta(days=(today.weekday()+2)%7),today
    if preset in ('month','thismonth','lastmonth','year'):
        y,m=j.year,j.month
        if preset=='lastmonth': y,m=(y-1,12) if m==1 else (y,m-1)
        if preset=='year': return jdatetime.date(y,1,1).togregorian(),jdatetime.date(y+1,1,1).togregorian()-timedelta(days=1)
        start=jdatetime.date(y,m,1).togregorian()
        end=jdatetime.date(y+1,1,1) if m==12 else jdatetime.date(y,m+1,1)
        return start,end.togregorian()-timedelta(days=1)
    return None,None
