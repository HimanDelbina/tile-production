from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.core.validators import MinValueValidator, RegexValidator

class NamedBase(models.Model):
    name = models.CharField('نام',max_length=120,unique=True)
    active = models.BooleanField('فعال',default=True)
    class Meta:
        abstract = True
        ordering = ['name']
    def __str__(self): return self.name

class Factory(NamedBase):
    class Meta(NamedBase.Meta): verbose_name='کارخانه'; verbose_name_plural='کارخانه‌ها'



class Size(models.Model):
    width = models.PositiveIntegerField('عرض (سانتی‌متر)',validators=[MinValueValidator(1)])
    length = models.PositiveIntegerField('طول (سانتی‌متر)',validators=[MinValueValidator(1)])
    active = models.BooleanField('فعال',default=True)
    class Meta:
        ordering=['width','length']
        constraints=[models.UniqueConstraint(fields=['width','length'],name='unique_tile_size'),models.CheckConstraint(condition=Q(width__gt=0,length__gt=0),name='positive_size')]
        verbose_name='سایز'; verbose_name_plural='سایزها'
    def __str__(self): return f'{self.width} × {self.length}'

class Grade(NamedBase):
    rank = models.PositiveIntegerField('ترتیب درجه',unique=True)
    color = models.CharField('رنگ نمودار',max_length=7,default='#159b9a',validators=[RegexValidator(r'^#[0-9a-fA-F]{6}$','رنگ شش‌رقمی معتبر وارد کنید.')])
    class Meta(NamedBase.Meta): ordering=['rank']; verbose_name='درجه'; verbose_name_plural='درجات'

class Profile(models.Model):
    ROLES=[('admin','مدیر سامانه'),('entry','کاربر ثبت تولید'),('viewer','مدیر گزارش‌گیر')]
    user = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='profile')
    role = models.CharField('نقش',choices=ROLES,max_length=10,default='viewer')
    factories = models.ManyToManyField(Factory,verbose_name='کارخانه‌های مجاز',blank=True)

class Production(models.Model):
    factory=models.ForeignKey(Factory,on_delete=models.PROTECT,verbose_name='کارخانه')
    date=models.DateField('تاریخ تولید')
    size=models.ForeignKey(Size,on_delete=models.PROTECT,verbose_name='سایز')
    grade=models.ForeignKey(Grade,on_delete=models.PROTECT,verbose_name='درجه')
    technical_type = models.ForeignKey('TechnicalType', null=True, blank=True, on_delete=models.SET_NULL, verbose_name='نوع فنی')
    area=models.DecimalField('متراژ (مترمربع)',max_digits=14,decimal_places=2,validators=[MinValueValidator(Decimal('0.01'))])
    notes=models.TextField('توضیحات',blank=True,max_length=2000)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='productions',verbose_name='ثبت‌کننده')
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    deleted_at=models.DateTimeField(null=True,blank=True)
    version=models.PositiveIntegerField(default=1)
    class Meta:
        ordering=['-date','-id']
        indexes=[models.Index(fields=['factory','date']),models.Index(fields=['deleted_at','date'])]
    def snapshot(self):
        from .dates import jalali
        return {'شناسه':str(self.pk),'کارخانه':str(self.factory),'تاریخ تولید':jalali(self.date),'سایز':str(self.size),'درجه':str(self.grade),'متراژ':str(self.area),'توضیحات':self.notes,'ثبت‌کننده':self.created_by.get_full_name() or self.created_by.username,'نسخه':self.version,'وضعیت':'حذف‌شده' if self.deleted_at else 'فعال'}

class Audit(models.Model):
    production=models.ForeignKey(Production,on_delete=models.PROTECT)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=12,choices=[('create','ایجاد'),('update','ویرایش'),('delete','حذف')])
    at=models.DateTimeField(auto_now_add=True)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    class Meta: ordering=['-at']

class Submission(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    key=models.UUIDField()
    digest=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['user','key'],name='unique_submission')]

# New models for Excel import feature
import uuid

class TechnicalType(models.Model):
    name = models.CharField('نام فنی', max_length=200, unique=True)
    description = models.TextField('شرح', blank=True)

    class Meta:
        verbose_name = 'نوع فنی'
        verbose_name_plural = 'انواع فنی'
        ordering = ['name']

    def __str__(self):
        return self.name

class ProductionImportBatch(models.Model):
    factory = models.ForeignKey(Factory, on_delete=models.PROTECT, verbose_name='کارخانه')
    date = models.DateField('تاریخ تولید')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name='بارگذار')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='زمان بارگذاری')
    original_file = models.FileField('فایل اکسِل', upload_to='imports/')
    sheet_name = models.CharField('نام شیت', max_length=200, blank=True)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name='توکن')
    status = models.CharField('وضعیت', max_length=20, choices=[('pending', 'در انتظار بررسی'), ('confirmed', 'ثبت شده')], default='pending')
    confirmed_at = models.DateTimeField('زمان ثبت نهایی', null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='confirmed_batches', verbose_name='تأییدکننده')
    file_hash = models.CharField('هش فایل', max_length=64, blank=True)

    class Meta:
        verbose_name = 'دسته بارگذاری تولید از اکسل'
        verbose_name_plural = 'دسته‌های بارگذاری تولید از اکسل'
        ordering = ['-uploaded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['factory', 'date', 'file_hash', 'sheet_name'],
                condition=models.Q(status='confirmed', file_hash__gt=''),
                name='unique_confirmed_import_batch'
            )
        ]

    def __str__(self):
        return f"Batch {self.pk} - {self.factory} - {self.date}"

class ProductionImportRow(models.Model):
    batch = models.ForeignKey(ProductionImportBatch, related_name='rows', on_delete=models.CASCADE, verbose_name='دسته بارگذاری')
    excel_row = models.PositiveIntegerField('ردیف اکسل')
    raw_description = models.TextField('شرح خام')
    parsed_description = models.TextField('شرح پردازش‌شده', blank=True)
    production_quantity = models.DecimalField('جمع تولید', max_digits=14, decimal_places=2, null=True, blank=True)
    extracted_width = models.PositiveIntegerField('عرض استخراج‌شده', null=True, blank=True)
    extracted_length = models.PositiveIntegerField('طول استخراج‌شده', null=True, blank=True)
    extracted_grade_code = models.CharField('کد درجه استخراج‌شده', max_length=50, blank=True)
    extracted_technical_type_name = models.CharField('نوع فنی استخراج‌شده', max_length=200, blank=True)
    extracted_piece_area = models.DecimalField('ضریب مساحت واحد تولید استخراج‌شده', max_digits=10, decimal_places=4, null=True, blank=True)
    is_reversed_size = models.BooleanField('تطبیق سایز معکوس', default=False)
    size = models.ForeignKey(Size, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='سایز')
    grade = models.ForeignKey(Grade, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='درجه')
    technical_type = models.ForeignKey(TechnicalType, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='نوع فنی')
    area = models.DecimalField('متراژ', max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    notes = models.CharField('یادداشت', max_length=200, blank=True)
    status = models.CharField('وضعیت', max_length=20, choices=[('pending','در انتظار'),('error','خطا'),('ok','تأیید شده')], default='pending')
    error_message = models.TextField('پیام خطا', blank=True)
    source_errors = models.JSONField('خطاهای منبع فایل', default=list, blank=True)
    edited_data = models.JSONField('داده‌های اصلاح‌شده', blank=True, null=True)
    production = models.ForeignKey(Production, null=True, blank=True, on_delete=models.SET_NULL, related_name='import_rows', verbose_name='تولید نهایی')

    class Meta:
        verbose_name = 'ردیف بارگذاری تولید'
        verbose_name_plural = 'ردیف‌های بارگذاری تولید'
        ordering = ['excel_row']

    def __str__(self):
        return f"Row {self.excel_row} (Batch {self.batch.pk})"

