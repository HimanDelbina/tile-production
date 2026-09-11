from django.core.management.base import BaseCommand
from django.db import transaction
from production.models import Factory,Grade,Size
class Command(BaseCommand):
    help='تعریف اطلاعات پایه اولیه؛ بدون ساخت کاربر یا تولید نمونه'
    @transaction.atomic
    def handle(self,*args,**kwargs):
        # Primary keys make reruns preserve renamed factories and grades.
        for pk,name in [(1,'کارخانه اول'),(2,'کارخانه دوم')]: Factory.objects.get_or_create(pk=pk,defaults={'name':name})
        for rank,color in [(1,'#159b9a'),(2,'#eba743'),(3,'#657dba')]:Grade.objects.get_or_create(rank=rank,defaults={'name':f'درجه {rank}','color':color})
        for w,l in [(60,120),(60,60),(100,100)]: Size.objects.get_or_create(width=w,length=l)
        from django.core.management.color import no_style
        from django.db import connection
        with connection.cursor() as cursor:
            for sql in connection.ops.sequence_reset_sql(no_style(),[Factory]): cursor.execute(sql)
        self.stdout.write(self.style.SUCCESS('اطلاعات پایه آماده شد. تولید نمونه‌ای ساخته نشد.'))
