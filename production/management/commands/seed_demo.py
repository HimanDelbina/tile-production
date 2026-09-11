import os,uuid,random
from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand,CommandError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.db import transaction
from production.models import Production,Factory,Grade,Size
from production.services import create_batch
from production.dates import parse_jalali
class Command(BaseCommand):
    help='ساخت داده آزمایشی فقط در دیتابیس خالی و با ALLOW_DEMO_DATA=1'
    def add_arguments(self,parser): parser.add_argument('--username',required=True);parser.add_argument('--extended',action='store_true')
    @transaction.atomic
    def handle(self,*args,**options):
        if os.getenv('ALLOW_DEMO_DATA')!='1': raise CommandError('برای دیتابیس آزمایشی ALLOW_DEMO_DATA=1 را تنظیم کنید.')
        if Production.objects.exists(): raise CommandError('دیتابیس دارای تولید است؛ داده نمونه اضافه نشد.')
        user=get_user_model().objects.get(username=options['username'])
        if not user.is_superuser: raise CommandError('کاربر باید مدیر اولیه باشد.')
        call_command('setup_basics')
        size=Size.objects.get(width=60,length=120);day=parse_jalali('1405/06/18')
        for factory,areas in zip(Factory.objects.order_by('id')[:2],[(800,200),(300,200)]):
            create_batch(user,factory,day,[{'size':size,'grade':Grade.objects.get(rank=i),'area':Decimal(a),'notes':'داده آزمایشی'} for i,a in enumerate(areas,1)],uuid.uuid4())
        if options['extended']:
            rng=random.Random(42)
            for n in range(1,18):
                for f in Factory.objects.order_by('id')[:2]:
                    rows=[{'size':rng.choice(list(Size.objects.all())),'grade':g,'area':Decimal(rng.randint(40,700)),'notes':'داده آزمایشی'} for g in Grade.objects.all()]
                    create_batch(user,f,day-timedelta(days=n),rows,uuid.uuid4())
        self.stdout.write(self.style.SUCCESS('داده آزمایشی ایجاد شد. این دیتابیس برای کار عملیاتی استفاده نشود.'))
