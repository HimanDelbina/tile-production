from decimal import Decimal
from django import template
from django.utils import timezone
from production.dates import jalali
register=template.Library()
@register.filter
def fa(value): return str(value).translate(str.maketrans('0123456789,.','۰۱۲۳۴۵۶۷۸۹٬٫'))
@register.filter
def num(value):
    if value is None: return '—'
    try: return fa(f'{Decimal(value):,.2f}')
    except Exception: return fa(value)
@register.filter
def cell(value): return num(value) if isinstance(value,(Decimal,float)) else fa('—' if value is None else value)
@register.filter
def jdate(value): return fa(jalali(value))
@register.filter
def jtime(value):
    if not value: return ''
    local=timezone.localtime(value)
    return fa(jalali(local.date())+' · '+local.strftime('%H:%M'))
@register.simple_tag(takes_context=True)
def query_page(context,page):
    p=context['params'].copy();p['page']=page;return '?'+p.urlencode()
