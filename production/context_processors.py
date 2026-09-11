from django.utils import timezone
from .permissions import role,can_write
from .dates import jalali

def shell(request):
    return {'app_role':role(request.user),'can_write':can_write(request.user),'today_jalali':jalali(timezone.localdate())}
