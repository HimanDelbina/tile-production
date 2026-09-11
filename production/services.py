import hashlib, json
from django.db import transaction
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.utils import timezone
from .models import Production, Audit, Submission
from .permissions import can_write, factories_for, records_for

def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()

def duplicate_rows(user,factory,date,rows):
    seen=set(); duplicates=[]
    for i,row in enumerate(rows,1):
        sig=tuple(str(row[k]) for k in ('size','grade','area','notes'))
        if sig in seen or records_for(user).filter(factory=factory,date=date,**row).exists(): duplicates.append(i)
        seen.add(sig)
    return duplicates

@transaction.atomic
def create_batch(user,factory,date,rows,token):
    if not can_write(user) or not factories_for(user).filter(pk=factory.pk,active=True).exists(): raise PermissionDenied
    # Serializes all mutations for this user. PostgreSQL row lock + UNIQUE is the replay guard.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    digest=fingerprint({'factory':factory.pk,'date':date,'rows':rows})
    previous=Submission.objects.filter(user=user,key=token).first()
    if previous:
        if previous.digest!=digest: raise ValidationError('شناسه ارسال قبلاً برای اطلاعات دیگری استفاده شده است. فرم تازه باز کنید.')
        return False
    Submission.objects.create(user=user,key=token,digest=digest)
    for data in rows:
        obj=Production(factory=factory,date=date,created_by=user,**data)
        obj.full_clean(); obj.save()
        Audit.objects.create(production=obj,actor=user,action='create',after=obj.snapshot())
    return True

@transaction.atomic
def change_record(user,pk,data=None,version=None,delete=False):
    if not can_write(user): raise PermissionDenied
    obj=records_for(user).select_for_update(of=('self',)).get(pk=pk)
    if obj.version != version: raise ValidationError('این رکورد توسط کاربر دیگری تغییر کرده است. صفحه را تازه کنید.')
    before=obj.snapshot()
    if delete: obj.deleted_at=timezone.now()
    else:
        for key,value in data.items(): setattr(obj,key,value)
        if not factories_for(user).filter(pk=obj.factory_id).exists(): raise PermissionDenied
        obj.full_clean()
    obj.version+=1; obj.save()
    Audit.objects.create(production=obj,actor=user,action='delete' if delete else 'update',before=before,after=obj.snapshot())
    return obj
