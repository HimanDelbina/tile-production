from django.core.exceptions import PermissionDenied
from .models import Factory, Production

def role(user):
    if not user.is_authenticated: return ''
    if user.is_superuser: return 'admin'
    try: return user.profile.role
    except Exception: return ''

def admin_required(user):
    if role(user) != 'admin': raise PermissionDenied

def can_write(user): return role(user) in ('admin','entry')

def factories_for(user):
    if role(user)=='admin': return Factory.objects.all()
    if role(user) not in ('entry','viewer'): return Factory.objects.none()
    return user.profile.factories.all()

def records_for(user):
    return Production.objects.filter(deleted_at__isnull=True,factory__in=factories_for(user)).select_related('factory','size','grade','created_by','technical_type')

def can_manage_batch(user, batch):
    if not can_write(user):
        return False
    if role(user) == 'admin':
        return True
    if not factories_for(user).filter(pk=batch.factory_id, active=True).exists():
        return False
    return batch.uploaded_by_id == user.pk

