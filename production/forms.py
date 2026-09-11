from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import Factory, Size, Grade, Production, Profile, TechnicalType
from .permissions import factories_for, can_write
from .dates import normalize,parse_jalali,jalali

class JalaliField(forms.DateField):
    widget=forms.TextInput(attrs={'class':'jalali','placeholder':'۱۴۰۵/۰۶/۱۸','autocomplete':'off','inputmode':'numeric'})
    def to_python(self,value):
        if value in self.empty_values: return None
        if hasattr(value,'year'): return value
        return parse_jalali(value)
    def prepare_value(self,value):
        return jalali(value) if hasattr(value,'year') else value

class DecimalInput(forms.DecimalField):
    def to_python(self,value): return super().to_python(normalize(value) if value not in self.empty_values else value)

class ProductionForm(forms.ModelForm):
    area=DecimalInput(label='متراژ (مترمربع)',max_digits=14,decimal_places=2,min_value=Decimal('.01'),widget=forms.TextInput(attrs={'inputmode':'decimal','class':'area-input','placeholder':'۰٫۰۰'}))
    class Meta:
        model=Production
        fields=['size','grade','area','notes']
        widgets={'notes':forms.TextInput(attrs={'placeholder':'اختیاری'})}

class BatchHeader(forms.Form):
    factory=forms.ModelChoiceField(label='کارخانه',queryset=Factory.objects.none())
    date=JalaliField(label='تاریخ تولید')
    token=forms.UUIDField(widget=forms.HiddenInput)
    confirm_duplicate=forms.BooleanField(required=False,label='ثبت مجدد ردیف‌های مشابه را تأیید می‌کنم')
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['factory'].queryset=factories_for(user).filter(active=True)

RowSet=forms.formset_factory(ProductionForm,extra=0,can_delete=True,max_num=100,validate_max=True,min_num=1,validate_min=True)

GROUPS=[('detail','ریز تولیدات'),('day','خلاصه روزانه'),('month','خلاصه ماهانه شمسی'),('year','خلاصه سالانه شمسی'),('factory','مقایسه کارخانه‌ها'),('size','خلاصه سایزها'),('grade','خلاصه درجات'),('type','نوع کاشی: سایز + درجه'),('matrix','ماتریس درجات')]
class FilterForm(forms.Form):
    start=JalaliField(label='از تاریخ',required=False)
    end=JalaliField(label='تا تاریخ',required=False)
    factory=forms.ModelMultipleChoiceField(label='کارخانه‌ها',queryset=Factory.objects.none(),required=False)
    size=forms.ModelMultipleChoiceField(label='سایزها',queryset=Size.objects.all(),required=False)
    grade=forms.ModelMultipleChoiceField(label='درجات',queryset=Grade.objects.all(),required=False)
    minimum=DecimalInput(label='حداقل متراژ ردیف',required=False,max_digits=14,decimal_places=2,min_value=0)
    maximum=DecimalInput(label='حداکثر متراژ ردیف',required=False,max_digits=14,decimal_places=2,min_value=0)
    author=forms.ModelChoiceField(label='ثبت‌کننده',queryset=get_user_model().objects.none(),required=False)
    q=forms.CharField(label='جست‌وجو',required=False,max_length=200,widget=forms.TextInput(attrs={'placeholder':'توضیحات…'}))
    group=forms.ChoiceField(label='گروه‌بندی',choices=GROUPS,required=False)
    order=forms.ChoiceField(label='مرتب‌سازی',choices=[('new','جدیدترین'),('old','قدیمی‌ترین'),('area_desc','بیشترین متراژ'),('area_asc','کمترین متراژ')],required=False)
    trend=forms.ChoiceField(label='روند نمودار',choices=[('day','روزانه'),('month','ماهانه شمسی')],required=False)
    page_size=forms.TypedChoiceField(label='ردیف در صفحه',choices=[(25,'۲۵'),(50,'۵۰'),(100,'۱۰۰')],coerce=int,required=False,empty_value=25)
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['factory'].queryset=factories_for(user)
        self.fields['author'].queryset=get_user_model().objects.filter(productions__factory__in=factories_for(user)).distinct()
        for name in ('factory','size','grade','author'):
            self.fields[name].widget.attrs['class']='searchable'
    def clean(self):
        d=super().clean()
        if d.get('start') and d.get('end') and d['start']>d['end']: self.add_error('end','پایان بازه نباید قبل از شروع باشد.')
        if d.get('minimum') is not None and d.get('maximum') is not None and d['minimum']>d['maximum']: self.add_error('maximum','حداکثر متراژ باید بزرگ‌تر یا مساوی حداقل باشد.')
        return d

class ManagementFilterForm(forms.Form):
    start = JalaliField(label='از تاریخ', required=False)
    end = JalaliField(label='تا تاریخ', required=False)
    factory = forms.ModelMultipleChoiceField(label='کارخانه‌ها', queryset=Factory.objects.none(), required=False)
    size = forms.ModelMultipleChoiceField(label='سایزها', queryset=Size.objects.none(), required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['factory'].queryset = factories_for(user)
        self.fields['size'].queryset = Size.objects.all()
        for name in ('factory', 'size'):
            self.fields[name].widget.attrs['class'] = 'searchable'

    def clean(self):
        d = super().clean()
        if d.get('start') and d.get('end') and d['start'] > d['end']:
            self.add_error('end', 'پایان بازه نباید قبل از شروع تاریخ باشد.')
        return d

class UserForm(forms.Form):
    username=forms.CharField(label='نام کاربری',max_length=150,validators=get_user_model()._meta.get_field('username').validators)
    first_name=forms.CharField(label='نام',required=False,max_length=150)
    last_name=forms.CharField(label='نام خانوادگی',required=False,max_length=150)
    password=forms.CharField(label='رمز عبور جدید',required=False,widget=forms.PasswordInput,help_text='برای حفظ رمز فعلی خالی بگذارید.')
    role=forms.ChoiceField(label='نقش',choices=Profile.ROLES)
    factories=forms.ModelMultipleChoiceField(label='کارخانه‌های مجاز',queryset=Factory.objects.all(),required=False)
    is_active=forms.BooleanField(label='حساب فعال',required=False,initial=True)
    def __init__(self,*args,instance=None,**kwargs):
        self.instance=instance
        super().__init__(*args,**kwargs)
    def clean(self):
        d=super().clean()
        if get_user_model().objects.filter(username=d.get('username')).exclude(pk=self.instance.pk if self.instance else None).exists(): self.add_error('username','این نام کاربری قبلاً استفاده شده است.')
        if not self.instance and not d.get('password'): self.add_error('password','رمز عبور الزامی است.')
        if d.get('password'):
            u=get_user_model()(username=d.get('username',''),first_name=d.get('first_name',''),last_name=d.get('last_name',''))
            try: validate_password(d['password'],u)
            except ValidationError as e: self.add_error('password',e)
        return d

class ExcelUploadForm(forms.Form):
    factory = forms.ModelChoiceField(label='کارخانه', queryset=Factory.objects.none())
    date = JalaliField(label='تاریخ تولید')
    file = forms.FileField(label='فایل اکسل')
    sheet_name = forms.CharField(label='نام شیت (اختیاری)', required=False, max_length=200)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and can_write(user):
            self.fields['factory'].queryset = factories_for(user).filter(active=True)
        else:
            self.fields['factory'].queryset = Factory.objects.none()

    def clean_file(self):
        f = self.cleaned_data.get('file')
        if f:
            from .importing.validation import validate_file_limits
            validate_file_limits(f)
        return f


class ImportRowEditForm(forms.Form):
    row_id = forms.IntegerField(widget=forms.HiddenInput)
    size = forms.ModelChoiceField(
        label='سایز',
        queryset=Size.objects.filter(active=True),
        required=True,
        error_messages={'required': 'انتخاب سایز الزامی است.'},
        widget=forms.Select(attrs={'style': 'width: 100%; min-width: 110px; font-size: 0.85rem; padding: 4px;'})
    )
    grade = forms.ModelChoiceField(
        label='درجه',
        queryset=Grade.objects.filter(active=True),
        required=True,
        error_messages={'required': 'انتخاب درجه الزامی است.'},
        widget=forms.Select(attrs={'style': 'width: 100%; min-width: 95px; font-size: 0.85rem; padding: 4px;'})
    )
    technical_type = forms.ModelChoiceField(
        label='نوع فنی',
        queryset=TechnicalType.objects.all(),
        required=False,
        widget=forms.Select(attrs={'style': 'width: 100%; min-width: 130px; font-size: 0.85rem; padding: 4px;'})
    )
    area = forms.DecimalField(
        label='متراژ',
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.01'),
        error_messages={'required': 'متراژ الزامی است.', 'min_value': 'متراژ باید بزرگ‌تر از صفر باشد.'},
        widget=forms.TextInput(attrs={'style': 'width: 90px; font-size: 0.85rem; padding: 4px; text-align: left; direction: ltr;'})
    )
    notes = forms.CharField(label='یادداشت', required=False, max_length=200, widget=forms.TextInput(attrs={'style': 'width: 100%; font-size: 0.85rem; padding: 4px;'}))
