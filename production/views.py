import os, calendar, uuid, hashlib, re
import jdatetime
from django import forms
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse,JsonResponse,HttpResponseNotAllowed
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Factory,Size,Grade,Profile,Production,Audit,Submission
from .forms import BatchHeader,RowSet,ProductionForm,FilterForm,UserForm,ManagementFilterForm
from .dates import period,jalali,normalize
from .permissions import admin_required,can_write,factories_for,records_for,role,can_manage_batch
from .services import create_batch,change_record,duplicate_rows
from .reporting import summarize,report_table
from .management_reporting import get_management_report_data
from openpyxl import load_workbook
from .importing.parser import parse_description
from .importing.matcher import match_and_evaluate_row, match_size, match_grade, match_technical_type
from .importing.reader import read_excel_import_file
from .forms import ExcelUploadForm, ImportRowEditForm
from .models import ProductionImportBatch, ProductionImportRow, TechnicalType, Size, Grade

def report_context(request,dashboard=False):
    params=request.GET.copy()
    preset=params.pop('preset',None)
    if preset:
        start,end=period(preset[-1])
        if start: params['start']=jalali(start);params['end']=jalali(end)
    if dashboard and not params:
        start,end=period('month');params['start']=jalali(start);params['end']=jalali(end)
    form=FilterForm(params,user=request.user)
    valid=form.is_valid()
    data=form.cleaned_data if valid else {}
    summary=summarize(request.user,data,params) if valid else None
    table=report_table(summary,data) if valid else None
    page=Paginator(table['body'],data.get('page_size') or 25).get_page(request.GET.get('page')) if table else None
    active=[]
    if valid:
        for key,value in data.items():
            if value in (None,'',[]) or key in ('group','order','page_size','trend'): continue
            if hasattr(value,'exists'):
                if not value.exists(): continue
                display='، '.join(map(str,value))
            elif key in ('start','end'): display=jalali(value)
            else: display=str(value)
            active.append({'label':form.fields[key].label,'value':display})
    params.pop('page',None)
    return {'filter_form':form,'summary':summary,'table':table,'page':page,'params':params,'query':params.urlencode(),'active_filters':active,'valid':valid,'title':'نمای کلی تولید' if dashboard else 'گزارش‌های تولید','is_dashboard':dashboard}

@login_required
def management_report(request):
    params = request.GET.copy()
    preset = params.pop('preset', None)
    if preset:
        preset_name = preset[-1] if isinstance(preset, list) else preset
        if preset_name in ('month', 'thismonth'):
            today = timezone.localdate()
            j = jdatetime.date.fromgregorian(date=today)
            start = jdatetime.date(j.year, j.month, 1).togregorian()
            end = today
        else:
            start, end = period(preset_name)
        if start and end:
            params['start'] = jalali(start)
            params['end'] = jalali(end)
    elif 'start' not in params and 'end' not in params:
        start, end = period('yesterday')
        params['start'] = jalali(start)
        params['end'] = jalali(end)

    form = ManagementFilterForm(params, user=request.user)
    valid = form.is_valid()
    data = form.cleaned_data if valid else {}
    report = get_management_report_data(request.user, data, params) if valid else None

    active_summary = {}
    if valid:
        start_val = data.get('start')
        end_val = data.get('end')
        if start_val and end_val:
            if start_val == end_val:
                active_summary['date_range'] = jalali(start_val)
            else:
                active_summary['date_range'] = f"از {jalali(start_val)} تا {jalali(end_val)}"
        elif start_val:
            active_summary['date_range'] = f"از {jalali(start_val)}"
        elif end_val:
            active_summary['date_range'] = f"تا {jalali(end_val)}"
        else:
            active_summary['date_range'] = "تمام تاریخ‌ها"

        if data.get('factory'):
            active_summary['factories'] = '، '.join(f.name for f in data['factory'])
        else:
            active_summary['factories'] = 'همه کارخانه‌های مجاز'

        if data.get('size'):
            active_summary['sizes'] = '، '.join(str(s) for s in data['size'])

    allowed_factories = factories_for(request.user).order_by('name')
    selected_factories = data.get('factory') if valid else None
    selected_factory_pks = set(selected_factories.values_list('pk', flat=True)) if selected_factories else set()

    p_all = params.copy()
    p_all.pop('factory', None)
    url_all_factories = f"{request.path}?{p_all.urlencode()}" if p_all else request.path

    quick_factory_buttons = []
    for f in allowed_factories:
        p_f = params.copy()
        p_f.setlist('factory', [str(f.pk)])
        is_active = (len(selected_factory_pks) == 1 and f.pk in selected_factory_pks)
        quick_factory_buttons.append({
            'pk': f.pk,
            'name': f.name,
            'url': f"{request.path}?{p_f.urlencode()}",
            'is_active': is_active,
        })

    is_all_factories_active = (len(selected_factory_pks) == 0 or len(selected_factory_pks) == allowed_factories.count())

    ctx = {
        'filter_form': form,
        'report': report,
        'valid': valid,
        'params': params,
        'query': params.urlencode(),
        'active_summary': active_summary,
        'title': 'گزارش مدیریتی',
        'quick_factory_buttons': quick_factory_buttons,
        'url_all_factories': url_all_factories,
        'is_all_factories_active': is_all_factories_active,
    }
    return render(request, 'production/management_report.html', ctx, status=200 if valid else 400)

@login_required
def dashboard(request):
    ctx=report_context(request,True)
    return render(request,'production/dashboard.html',ctx,status=200 if ctx['valid'] else 400)

@login_required
def reports(request):
    ctx=report_context(request)
    return render(request,'production/reports.html',ctx,status=200 if ctx['valid'] else 400)

@login_required
def create(request):
    if not can_write(request.user): raise PermissionDenied
    single=request.GET.get('mode')=='single'
    header=BatchHeader(request.POST or None,user=request.user,initial={'date':timezone.localdate(),'token':uuid.uuid4()})
    rowset=RowSet(request.POST or None,prefix='rows')
    warning=[]
    if request.method=='POST':
        hv=header.is_valid(); rv=rowset.is_valid()
        if hv and rv:
            rows=[{k:d[k] for k in ('size','grade','area','notes')} for d in rowset.cleaned_data if d and not d.get('DELETE')]
            h=header.cleaned_data
            warning=duplicate_rows(request.user,h['factory'],h['date'],rows)
            if not warning or h['confirm_duplicate'] or Submission.objects.filter(user=request.user,key=h['token']).exists():
                try:
                    saved=create_batch(request.user,h['factory'],h['date'],rows,h['token'])
                    messages.success(request,'تولید با موفقیت ثبت شد.' if saved else 'این درخواست قبلاً ثبت شده بود؛ رکورد تکراری ایجاد نشد.')
                    return redirect(request.get_full_path() if request.POST.get('next') else '/reports/')
                except ValidationError as e: header.add_error(None,e)
    return render(request,'production/create.html',{'title':'ثبت تولید تکی' if single else 'ثبت چندردیفی تولید','header':header,'rowset':rowset,'single':single,'warning':warning})

@login_required
def edit(request,pk):
    if not can_write(request.user): raise PermissionDenied
    obj=get_object_or_404(records_for(request.user),pk=pk)
    form=ProductionForm(request.POST or None,instance=obj)
    header=BatchHeader(request.POST or None,user=request.user,initial={'date':obj.date,'factory':obj.factory_id,'token':uuid.uuid4()})
    header.fields['factory'].queryset=factories_for(request.user).filter(Q(active=True)|Q(pk=obj.factory_id))
    original_version=obj.version
    if request.method=='POST':
        fv=form.is_valid();hv=header.is_valid()
        if fv and hv:
            try:
                version=int(request.POST.get('version','0'))
                change_record(request.user,pk,{**form.cleaned_data,'date':header.cleaned_data['date'],'factory':header.cleaned_data['factory']},version=version)
                messages.success(request,'تغییرات ذخیره شد.');return redirect('/reports/')
            except (ValidationError,ValueError) as e: form.add_error(None,e if isinstance(e,ValidationError) else 'نسخه رکورد معتبر نیست.')
    return render(request,'production/edit.html',{'title':'ویرایش تولید','form':form,'header':header,'obj':obj,'version':original_version})

@login_required
def delete(request,pk):
    if not can_write(request.user): raise PermissionDenied
    obj=get_object_or_404(records_for(request.user),pk=pk)
    if request.method=='POST':
        try:
            change_record(request.user,pk,version=int(request.POST.get('version','0')),delete=True)
            messages.success(request,'رکورد حذف شد؛ تاریخچه آن محفوظ است.');return redirect('/reports/')
        except (ValidationError,ValueError) as e: messages.error(request,str(e))
    return render(request,'production/delete.html',{'title':'تأیید حذف تولید','obj':obj})

@login_required
def history(request,pk):
    obj=get_object_or_404(Production.objects.filter(factory__in=factories_for(request.user)),pk=pk)
    return render(request,'production/history.html',{'title':'تاریخچه تولید','obj':obj,'events':obj.audit_set.select_related('actor').all()})

MASTER={'factories':(Factory,'کارخانه‌ها',['name','active']),'sizes':(Size,'سایزها',['width','length','active']),'grades':(Grade,'درجات',['name','rank','color','active'])}
@login_required
def master(request,kind='factories',pk=None):
    admin_required(request.user)
    if kind not in MASTER: raise PermissionDenied
    model,title,fields=MASTER[kind]
    obj=get_object_or_404(model,pk=pk) if pk else None
    Form=forms.modelform_factory(model,fields=fields)
    data=request.POST.copy() if request.method=='POST' else None
    if data:
        for k in ('width','length','rank'):
            if k in data: data[k]=normalize(data[k])
    form=Form(data,instance=obj)
    if request.method=='POST' and form.is_valid():
        form.save();messages.success(request,'اطلاعات پایه ذخیره شد.');return redirect('master',kind=kind)
    return render(request,'production/master.html',{'title':'اطلاعات پایه · '+title,'kind':kind,'form':form,'items':model.objects.all(),'editing':obj,'master_tabs':[(k,v[1]) for k,v in MASTER.items()]})

@login_required
def users(request,pk=None):
    admin_required(request.user)
    obj=get_object_or_404(get_user_model(),pk=pk) if pk else None
    initial={}
    if obj:
        initial={k:getattr(obj,k) for k in ('username','first_name','last_name','is_active')}
        initial.update(role=role(obj),factories=list(factories_for(obj)))
    form=UserForm(request.POST or None,initial=initial,instance=obj)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        # Protect the initial superuser and prevent self-lockout through this UI.
        if obj and (obj.is_superuser or obj.pk==request.user.pk) and (d['role']!='admin' or not d['is_active']):
            form.add_error(None,'غیرفعال‌کردن یا کاهش نقش مدیر اولیه و حساب خودتان در این صفحه مجاز نیست.')
        else:
            with transaction.atomic():
                obj=obj or get_user_model()()
                for k in ('username','first_name','last_name','is_active'): setattr(obj,k,d[k])
                if d['password']: obj.set_password(d['password'])
                obj.save();profile,_=Profile.objects.get_or_create(user=obj)
                profile.role=d['role'];profile.save();profile.factories.set(d['factories'])
            messages.success(request,'حساب کاربری ذخیره شد.');return redirect('users')
    return render(request,'production/users.html',{'title':'مدیریت کاربران','form':form,'items':get_user_model().objects.select_related('profile').all(),'editing':obj})

@login_required
def calendar_month(request):
    today=jdatetime.date.fromgregorian(date=timezone.localdate())
    try:
        year=int(normalize(request.GET.get('year',today.year)));month=int(normalize(request.GET.get('month',today.month)))
        if not 1200<=year<=1600: raise ValueError()
        first=jdatetime.date(year,month,1)
    except (ValueError,TypeError): return JsonResponse({'error':'ماه یا سال معتبر نیست.'},status=400)
    nextmonth=jdatetime.date(year+1,1,1) if month==12 else jdatetime.date(year,month+1,1)
    days=(nextmonth.togregorian()-first.togregorian()).days
    return JsonResponse({'year':year,'month':month,'offset':first.weekday(),'days':days,'today':today.strftime('%Y/%m/%d')})

@login_required
def export(request,kind):
    ctx=report_context(request)
    if not ctx['valid']: return render(request,'production/reports.html',ctx,status=400)
    if kind=='xlsx':
        from .exports import excel
        return excel(ctx)
    if kind in ('pdf','print'):
        from .exports import print_context,pdf,prepare_print
        ctx.update(print_context())
        if kind=='pdf':
            try:
                return pdf(ctx)
            except (OSError, ImportError):
                # WeasyPrint C-libraries (GTK/Pango/GObject) not found on host.
                # Gracefully fallback to print template with clear Persian guidance.
                messages.warning(
                    request,
                    'به دلیل عدم نصب کتابخانه‌های سیستمی GTK/GObject روی سرور ویندوز، پیش‌نمایش چاپ باز شد. '
                    'می‌توانید با زدن کلید «چاپ گزارش» یا فشردن Ctrl+P، گزینه «Save as PDF» مرورگر را انتخاب نمایید.'
                )
                p_ctx = prepare_print(ctx)
                p_ctx['weasyprint_missing'] = True
                return render(request, 'production/print.html', p_ctx)
        return render(request,'production/print.html',prepare_print(ctx))
    return HttpResponse(status=404)

def health(request):
    from django.db import connection
    try:
        with connection.cursor() as c: c.execute('SELECT 1')
        return JsonResponse({'status':'ok'})
    except Exception: return JsonResponse({'status':'unavailable'},status=503)

from .importing.validation import validate_import_row

# --- Excel import workflow views ---

@login_required
def import_upload(request):
    """Step 1: upload Excel file, validate permissions and file, parse rows and redirect to preview."""
    if not can_write(request.user):
        raise PermissionDenied
        
    form = ExcelUploadForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        uploaded_file = form.cleaned_data['file']
        file_bytes = uploaded_file.read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        uploaded_file.seek(0)
        
        factory = form.cleaned_data['factory']
        date = form.cleaned_data['date']
        sheet_name = (form.cleaned_data.get('sheet_name') or '').strip()
        
        # Check if identical file and sheet has already been confirmed for this factory and date
        if ProductionImportBatch.objects.filter(
            factory=factory, date=date, file_hash=file_hash, sheet_name=sheet_name, status='confirmed'
        ).exists():
            form.add_error(None, 'این فایل با این مشخصات برای این کارخانه و تاریخ قبلاً بارگذاری و ثبت نهایی شده است.')
            return render(request, 'production/import_upload.html', {'form': form})
            
        # Check if an existing pending batch already exists for this exact identity
        existing_pending = ProductionImportBatch.objects.filter(
            factory=factory, date=date, file_hash=file_hash, sheet_name=sheet_name, status='pending'
        ).first()
        if existing_pending and can_manage_batch(request.user, existing_pending):
            messages.info(request, 'این فایل قبلاً برای این کارخانه و تاریخ بارگذاری شده و در وضعیت پیش‌نمایش قرار دارد.')
            return redirect('import_preview', token=existing_pending.token)
            
        batch = ProductionImportBatch.objects.create(
            factory=factory,
            date=date,
            uploaded_by=request.user,
            original_file=uploaded_file,
            sheet_name=sheet_name,
            file_hash=file_hash,
            status='pending',
        )
        
        try:
            parsed_rows = read_excel_import_file(batch.original_file.path, batch.sheet_name)
        except ValidationError as e:
            batch.delete()
            form.add_error(None, e)
            return render(request, 'production/import_upload.html', {'form': form})
            
        for r in parsed_rows:
            parsed_desc = parse_description(r['raw_description'])
            eval_res = match_and_evaluate_row(
                parsed_desc,
                quantity=r['quantity'],
                area=r['area'],
                source_errors=r.get('source_errors'),
            )
            
            w, l = parsed_desc.get('size') if parsed_desc.get('size') else (None, None)
            ProductionImportRow.objects.create(
                batch=batch,
                excel_row=r['excel_row'],
                raw_description=r['raw_description'],
                parsed_description=parsed_desc.get('cleaned_description', ''),
                production_quantity=eval_res['quantity'],
                extracted_width=w,
                extracted_length=l,
                extracted_grade_code=parsed_desc.get('grade_code') or '',
                extracted_technical_type_name=parsed_desc.get('technical_type_name') or '',
                extracted_piece_area=parsed_desc.get('piece_area'),
                is_reversed_size=eval_res['is_reversed_size'],
                size=eval_res['size'],
                grade=eval_res['grade'],
                technical_type=eval_res['technical_type'],
                area=eval_res['area'] if eval_res['area'] is not None else Decimal('0.00'),
                notes='',
                status=eval_res['status'],
                error_message=eval_res['error_message'],
                source_errors=r.get('source_errors') or [],
            )
        return redirect('import_preview', token=batch.token)
        
    return render(request, 'production/import_upload.html', {'form': form})


@login_required
def import_preview(request, token):
    """Step 2: inspect parsed rows, create missing base data (admin only), reprocess, edit rows, and preview."""
    if not can_write(request.user):
        raise PermissionDenied
    batch = get_object_or_404(ProductionImportBatch, token=token)
    if not can_manage_batch(request.user, batch):
        raise PermissionDenied

    # Backfill file_hash if empty for legacy batches
    if not batch.file_hash and batch.original_file and os.path.exists(batch.original_file.path):
        with open(batch.original_file.path, 'rb') as f:
            batch.file_hash = hashlib.sha256(f.read()).hexdigest()
            batch.save(update_fields=['file_hash'])

    # STRICT IMMUTABILITY: Confirmed batch cannot be mutated by any POST action
    if batch.status == 'confirmed' and request.method == 'POST':
        messages.error(request, 'این نوبت ورود قبلاً ثبت نهایی شده است و امکان ویرایش یا پردازش مجدد آن وجود ندارد.')
        return redirect('import_preview', token=batch.token)

    # If rows don't exist yet, populate from file
    if not batch.rows.exists() and batch.status != 'confirmed':
        try:
            parsed_rows = read_excel_import_file(batch.original_file.path, batch.sheet_name)
            for r in parsed_rows:
                parsed_desc = parse_description(r['raw_description'])
                eval_res = match_and_evaluate_row(
                    parsed_desc,
                    quantity=r['quantity'],
                    area=r['area'],
                    source_errors=r.get('source_errors'),
                )
                w, l = parsed_desc.get('size') if parsed_desc.get('size') else (None, None)
                ProductionImportRow.objects.create(
                    batch=batch,
                    excel_row=r['excel_row'],
                    raw_description=r['raw_description'],
                    parsed_description=parsed_desc.get('cleaned_description', ''),
                    production_quantity=eval_res['quantity'],
                    extracted_width=w,
                    extracted_length=l,
                    extracted_grade_code=parsed_desc.get('grade_code') or '',
                    extracted_technical_type_name=parsed_desc.get('technical_type_name') or '',
                    extracted_piece_area=parsed_desc.get('piece_area'),
                    is_reversed_size=eval_res['is_reversed_size'],
                    size=eval_res['size'],
                    grade=eval_res['grade'],
                    technical_type=eval_res['technical_type'],
                    area=eval_res['area'] if eval_res['area'] is not None else Decimal('0.00'),
                    notes='',
                    status=eval_res['status'],
                    error_message=eval_res['error_message'],
                    source_errors=r.get('source_errors') or [],
                )
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect('import_upload')

    action = request.POST.get('action')

    # Action 1: Create missing base data (Admin only)
    if request.method == 'POST' and action == 'create_missing_base':
        admin_required(request.user)
        with transaction.atomic():
            batch = ProductionImportBatch.objects.select_for_update().get(pk=batch.pk)
            if batch.status == 'confirmed':
                messages.error(request, 'این نوبت قبلاً ثبت نهایی شده است و امکان تغییر ندارد.')
                return redirect('import_preview', token=batch.token)

            selected_sizes = request.POST.getlist('sizes')
            selected_techs = request.POST.getlist('tech_types')
            
            created_sizes = 0
            created_techs = 0
            
            for s_str in selected_sizes:
                m = re.search(r'(\d+)\s*[*xX×]\s*(\d+)', s_str)
                if m:
                    w, l = int(m.group(1)), int(m.group(2))
                    if not Size.objects.filter(Q(width=w, length=l) | Q(width=l, length=w)).exists():
                        Size.objects.create(width=w, length=l, active=True)
                        created_sizes += 1
                        
            for t_str in selected_techs:
                t_clean = t_str.strip()
                if t_clean and not TechnicalType.objects.filter(name__iexact=t_clean).exists():
                    TechnicalType.objects.create(name=t_clean)
                    created_techs += 1
                    
            # Immediately re-match all rows of this batch against updated base data
            for row in batch.rows.all():
                parsed = parse_description(row.raw_description)
                user_edited = row.edited_data or {}
                eval_res = match_and_evaluate_row(
                    parsed,
                    quantity=row.production_quantity,
                    area=Decimal(user_edited['area']) if user_edited.get('area') else row.area,
                    current_size=Size.objects.filter(pk=user_edited.get('size'), active=True).first() if user_edited.get('size') else None,
                    current_grade=Grade.objects.filter(pk=user_edited.get('grade'), active=True).first() if user_edited.get('grade') else None,
                    current_tech=TechnicalType.objects.filter(pk=user_edited.get('technical_type')).first() if user_edited.get('technical_type') else None,
                    user_edited_fields=user_edited if user_edited else None,
                    source_errors=row.source_errors,
                )
                row.size = eval_res['size']
                row.grade = eval_res['grade']
                row.technical_type = eval_res['technical_type']
                row.is_reversed_size = eval_res['is_reversed_size']
                row.status = eval_res['status']
                row.error_message = eval_res['error_message']
                row.save()
                
        messages.success(request, f"اطلاعات پایه ایجاد شد ({created_sizes} سایز، {created_techs} نوع فنی) و پیش‌نمایش به‌روزرسانی گردید.")
        return redirect('import_preview', token=batch.token)

    # Action 2: Reprocess previous preview (preserves manual overrides and source errors)
    if request.method == 'POST' and action == 'reprocess':
        with transaction.atomic():
            batch = ProductionImportBatch.objects.select_for_update().get(pk=batch.pk)
            if batch.status == 'confirmed':
                messages.error(request, 'این نوبت قبلاً ثبت نهایی شده است و امکان پردازش مجدد ندارد.')
                return redirect('import_preview', token=batch.token)
                
            for row in batch.rows.all():
                parsed = parse_description(row.raw_description)
                row.parsed_description = parsed.get('cleaned_description', '')
                w, l = parsed.get('size') if parsed.get('size') else (None, None)
                row.extracted_width = w
                row.extracted_length = l
                row.extracted_grade_code = parsed.get('grade_code') or ''
                row.extracted_technical_type_name = parsed.get('technical_type_name') or ''
                row.extracted_piece_area = parsed.get('piece_area')
                
                user_edited = row.edited_data or {}
                conflict_notes = []
                if user_edited.get('size') and row.extracted_width and row.extracted_length:
                    old_s = Size.objects.filter(pk=user_edited['size']).first()
                    if old_s and (old_s.width, old_s.length) not in ((row.extracted_width, row.extracted_length), (row.extracted_length, row.extracted_width)):
                        conflict_notes.append(f"تعارض: سایز دستی انتخاب‌شده ({old_s}) با سایز استخراج‌شده ({row.extracted_width}×{row.extracted_length}) مغایرت دارد.")
                        
                eval_res = match_and_evaluate_row(
                    parsed,
                    quantity=row.production_quantity,
                    area=Decimal(user_edited['area']) if user_edited.get('area') else row.area,
                    current_size=Size.objects.filter(pk=user_edited.get('size'), active=True).first() if user_edited.get('size') else None,
                    current_grade=Grade.objects.filter(pk=user_edited.get('grade'), active=True).first() if user_edited.get('grade') else None,
                    current_tech=TechnicalType.objects.filter(pk=user_edited.get('technical_type')).first() if user_edited.get('technical_type') else None,
                    user_edited_fields=user_edited if user_edited else None,
                    source_errors=row.source_errors,
                )
                row.size = eval_res['size']
                row.grade = eval_res['grade']
                row.technical_type = eval_res['technical_type']
                row.is_reversed_size = eval_res['is_reversed_size']
                row.status = eval_res['status']
                
                all_msgs = []
                if conflict_notes:
                    all_msgs.extend(conflict_notes)
                if eval_res['error_message']:
                    all_msgs.append(eval_res['error_message'])
                row.error_message = '؛ '.join(all_msgs)
                row.save()
                
        messages.success(request, 'پردازش مجدد با حفظ اصلاحات دستی انجام شد.')
        return redirect('import_preview', token=batch.token)

    # Action 3: Save manual edits from the formset table
    if request.method == 'POST' and (action == 'save_rows' or not action):
        with transaction.atomic():
            batch = ProductionImportBatch.objects.select_for_update().get(pk=batch.pk)
            if batch.status == 'confirmed':
                messages.error(request, 'این نوبت قبلاً ثبت نهایی شده است و امکان ذخیره تغییرات وجود ندارد.')
                return redirect('import_preview', token=batch.token)

            rows_by_id = {r.pk: r for r in batch.rows.all()}
            all_valid = True
            
            for row_pk, row_obj in rows_by_id.items():
                form = ImportRowEditForm(request.POST, prefix=f"r_{row_pk}")
                if form.is_valid():
                    cd = form.cleaned_data
                    row_obj.size = cd['size']
                    row_obj.grade = cd['grade']
                    row_obj.technical_type = cd['technical_type']
                    row_obj.area = cd['area']
                    row_obj.notes = cd['notes']
                    row_obj.edited_data = {
                        'size': cd['size'].pk if cd['size'] else None,
                        'grade': cd['grade'].pk if cd['grade'] else None,
                        'technical_type': cd['technical_type'].pk if cd['technical_type'] else None,
                        'area': str(cd['area']),
                        'notes': cd['notes'],
                    }
                    
                    parsed = parse_description(row_obj.raw_description)
                    eval_res = validate_import_row(
                        parsed_data=parsed,
                        quantity=row_obj.production_quantity,
                        area=cd['area'],
                        size_obj=cd['size'],
                        grade_obj=cd['grade'],
                        tech_obj=cd['technical_type'],
                        source_errors=row_obj.source_errors,
                        is_reversed_size=row_obj.is_reversed_size,
                    )
                    
                    row_obj.status = eval_res['status']
                    row_obj.error_message = eval_res['error_message']
                    if not eval_res['is_ok']:
                        all_valid = False
                    row_obj.save()
                else:
                    all_valid = False
                    row_obj.status = 'error'
                    err_list = []
                    for f, errs in form.errors.items():
                        err_list.extend(errs)
                    row_obj.error_message = '؛ '.join(err_list)
                    row_obj.save()
                    
            if all_valid:
                messages.success(request, 'تغییرات ردیف‌ها با موفقیت ذخیره شد.')
            else:
                messages.warning(request, 'تغییرات ذخیره شد، اما برخی ردیف‌ها دارای خطای اعتبارسنجی هستند.')
        return redirect('import_preview', token=batch.token)

    # Detect unique missing base data for suggestions
    missing_sizes_set = set()
    missing_techs_set = set()
    
    for r in batch.rows.all():
        if r.extracted_width and r.extracted_length:
            w, l = r.extracted_width, r.extracted_length
            if not Size.objects.filter(Q(width=w, length=l) | Q(width=l, length=w)).exists():
                missing_sizes_set.add((w, l))
        if r.extracted_technical_type_name:
            t_name = r.extracted_technical_type_name.strip()
            if t_name and not TechnicalType.objects.filter(name__iexact=t_name).exists():
                missing_techs_set.add(t_name)
                
    missing_sizes = [f"{w}×{l}" for w, l in sorted(missing_sizes_set)]
    missing_techs = sorted(missing_techs_set)
    
    # Prepare row items with initialized edit forms
    row_items = []
    is_confirmed = (batch.status == 'confirmed')
    for r in batch.rows.all():
        form = ImportRowEditForm(
            prefix=f"r_{r.pk}",
            initial={
                'row_id': r.pk,
                'size': r.size_id if r.size else None,
                'grade': r.grade_id if r.grade else None,
                'technical_type': r.technical_type_id if r.technical_type else None,
                'area': r.area,
                'notes': r.notes,
            }
        )
        if is_confirmed:
            for field in form.fields.values():
                field.disabled = True
                
        row_items.append({
            'row': r,
            'form': form,
            'extracted_size_display': f"{r.extracted_width} × {r.extracted_length}" if r.extracted_width and r.extracted_length else "—",
            'extracted_grade_display': r.extracted_grade_code or "—",
            'extracted_tech_display': r.extracted_technical_type_name or "—",
        })
        
    has_errors = batch.rows.filter(status='error').exists()
    can_confirm = (not has_errors) and (not is_confirmed)
    
    return render(request, 'production/import_preview.html', {
        'batch': batch,
        'row_items': row_items,
        'missing_sizes': missing_sizes,
        'missing_techs': missing_techs,
        'is_admin': (role(request.user) == 'admin'),
        'can_confirm': can_confirm,
        'has_errors': has_errors,
        'is_confirmed': is_confirmed,
    })


@require_POST
@login_required
def import_confirm(request, token):
    """Step 3: atomically validate rows, create Production and Audit records, and confirm batch."""
    if not can_write(request.user):
        raise PermissionDenied
        
    batch = get_object_or_404(ProductionImportBatch, token=token)
    if not can_manage_batch(request.user, batch):
        raise PermissionDenied
        
    with transaction.atomic():
        # 1. Row-lock on Factory to serialize confirmations for this factory
        Factory.objects.select_for_update().get(pk=batch.factory_id)

        # 2. Row-lock the batch record
        batch = ProductionImportBatch.objects.select_for_update().get(pk=batch.pk)
        
        # 3. Re-check user factory permissions
        if not factories_for(request.user).filter(pk=batch.factory_id, active=True).exists():
            raise PermissionDenied
            
        # 4. Replay guard: prevent duplicate confirmations of same batch
        if batch.status == 'confirmed':
            messages.warning(request, 'این نوبت ورود قبلاً ثبت نهایی شده است؛ رکورد تکراری ایجاد نشد.')
            return redirect('reports')
            
        # 5. Duplicate protection across distinct batches: check if another confirmed batch matches
        if not batch.file_hash and batch.original_file and os.path.exists(batch.original_file.path):
            with open(batch.original_file.path, 'rb') as f:
                batch.file_hash = hashlib.sha256(f.read()).hexdigest()
                batch.save(update_fields=['file_hash'])

        if batch.file_hash:
            conflict = ProductionImportBatch.objects.filter(
                factory=batch.factory,
                date=batch.date,
                file_hash=batch.file_hash,
                sheet_name=batch.sheet_name,
                status='confirmed'
            ).exclude(pk=batch.pk).first()
            if conflict:
                messages.error(
                    request,
                    f'نوبت ورود شماره {conflict.pk} با همین فایل و مشخصات قبلاً برای این کارخانه و تاریخ تأیید و ثبت نهایی شده است. برای جلوگیری از ثبت تکراری، این نوبت لغو گردید.'
                )
                return redirect('import_preview', token=batch.token)
            
        # 6. Re-validate ALL rows with unified validation service
        invalid_rows = []
        for row in batch.rows.all():
            parsed = parse_description(row.raw_description)
            eval_res = validate_import_row(
                parsed_data=parsed,
                quantity=row.production_quantity,
                area=row.area,
                size_obj=row.size,
                grade_obj=row.grade,
                tech_obj=row.technical_type,
                source_errors=row.source_errors,
                is_reversed_size=row.is_reversed_size,
            )
            if not eval_res['is_ok']:
                invalid_rows.append(row.excel_row)
                row.status = 'error'
                row.error_message = eval_res['error_message']
                row.save(update_fields=['status', 'error_message'])
                
        if invalid_rows:
            messages.error(request, f'ردیف‌های {", ".join(map(str, invalid_rows))} دارای خطا هستند و امکان ثبت نهایی وجود ندارد.')
            return redirect('import_preview', token=batch.token)
            
        # 7. Create Production and Audit records for each row
        confirmed_count = 0
        try:
            for row in batch.rows.select_related('size', 'grade', 'technical_type').all():
                prod = Production(
                    factory=batch.factory,
                    date=batch.date,
                    size=row.size,
                    grade=row.grade,
                    technical_type=row.technical_type,
                    area=row.area,
                    notes=row.notes or f"ورود از اکسل (ردیف {row.excel_row})",
                    created_by=request.user,
                )
                prod.full_clean()
                prod.save()
                
                row.production = prod
                row.save(update_fields=['production'])
                
                Audit.objects.create(
                    production=prod,
                    actor=request.user,
                    action='create',
                    before={},
                    after=prod.snapshot(),
                )
                confirmed_count += 1
                
            batch.status = 'confirmed'
            batch.confirmed_at = timezone.now()
            batch.confirmed_by = request.user
            batch.save(update_fields=['status', 'confirmed_at', 'confirmed_by'])
        except Exception as e:
            messages.error(request, f'خطا در ثبت پایگاه داده: {e}')
            return redirect('import_preview', token=batch.token)
            
    messages.success(request, f"نوبت بارگذاری {batch.pk} شامل {confirmed_count} ردیف تولید با موفقیت ثبت نهایی شد.")
    return redirect('reports')


@login_required
def import_file_download(request, token):
    """Securely download original imported excel file with authentication and factory permission check."""
    batch = get_object_or_404(ProductionImportBatch, token=token)
    if not can_manage_batch(request.user, batch) and role(request.user) != 'admin':
        raise PermissionDenied
    if not factories_for(request.user).filter(pk=batch.factory_id).exists():
        raise PermissionDenied
    if not batch.original_file or not os.path.exists(batch.original_file.path):
        return HttpResponse('فایل موردنظر در سرور یافت نشد.', status=404)
    from django.http import FileResponse
    return FileResponse(open(batch.original_file.path, 'rb'), as_attachment=True, filename=os.path.basename(batch.original_file.name))

# -------------------------------------------------------------------

def csrf_failure(request,reason=""):
    return render(request,"403.html",status=403)
