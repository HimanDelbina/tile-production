from django.core.management.base import BaseCommand
from django.db import transaction
from production.models import Factory,Grade,Size,Glaze,TechnicalType
class Command(BaseCommand):
    help='تعریف اطلاعات پایه اولیه؛ بدون ساخت کاربر یا تولید نمونه'
    @transaction.atomic
    def handle(self,*args,**kwargs):
        # Primary keys make reruns preserve renamed factories and grades.
        for pk,name in [(1,'کارخانه اول'),(2,'کارخانه دوم')]: Factory.objects.get_or_create(pk=pk,defaults={'name':name})
        for rank,color in [(1,'#159b9a'),(2,'#eba743')]:Grade.objects.get_or_create(rank=rank,defaults={'name':f'درجه {rank}','color':color})
        Grade.objects.filter(name='درجه 3').delete()
        if Grade.objects.filter(name='آنگرید').exists() and Grade.objects.filter(name='درجه 6').exists():
            Grade.objects.filter(name='درجه 6').update(rank=104)
            Grade.objects.filter(name='آنگرید').update(rank=3)
            Grade.objects.filter(name='درجه 6').update(rank=4)
        else:
            Grade.objects.get_or_create(name='آنگرید', defaults={'rank': 3, 'color': '#ec4899'})
            Grade.objects.get_or_create(name='درجه 6', defaults={'rank': 4, 'color': '#8b5cf6'})
        for w,l in [(60,120),(60,60),(100,100)]: Size.objects.get_or_create(width=w,length=l)
        for pk,name in [(1,'پولیش'),(2,'مات'),(3,'براق')]: Glaze.objects.get_or_create(pk=pk,defaults={'name':name})
        for name in ['10MIL', '12MIL', '9.5MIL', '8MIL', '14MIL', '20MIL']: TechnicalType.objects.get_or_create(name=name)
        from django.core.management.color import no_style
        from django.db import connection
        with connection.cursor() as cursor:
            for sql in connection.ops.sequence_reset_sql(no_style(),[Factory,Glaze]): cursor.execute(sql)
        self.stdout.write(self.style.SUCCESS('اطلاعات پایه آماده شد. تولید نمونه‌ای ساخته نشد.'))
