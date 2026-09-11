from collections import defaultdict
from decimal import Decimal
from datetime import timedelta
from urllib.parse import urlencode
from django.db.models import Q
from .models import Grade
from .permissions import records_for,factories_for
from .dates import jalali
ZERO=Decimal('0')

def percentage(n,d): return n/d*100 if d else None

def filtered(user,data,ignore_grade=False):
    q=records_for(user)
    for field in ('factory','size','grade'):
        if field=='grade' and ignore_grade: continue
        if data.get(field): q=q.filter(**{field+'__in':data[field]})
    if data.get('start'): q=q.filter(date__gte=data['start'])
    if data.get('end'): q=q.filter(date__lte=data['end'])
    if data.get('author'): q=q.filter(created_by=data['author'])
    if data.get('minimum') is not None: q=q.filter(area__gte=data['minimum'])
    if data.get('maximum') is not None: q=q.filter(area__lte=data['maximum'])
    if data.get('q'): q=q.filter(notes__icontains=data['q'])
    if data.get('technical_type'):
        tt = data['technical_type']
        if isinstance(tt, (list, set, tuple)): q = q.filter(technical_type__in=tt)
        else: q = q.filter(technical_type=tt)
    return q

def drill(params,**kwargs):
    p=params.copy()
    for k,v in kwargs.items():
        if v is None: p.pop(k,None)
        else: p[k]=str(v)
    p['group']='detail';p.pop('page',None)
    return '/reports/?'+p.urlencode()

def summarize(user,data,params):
    rows=list(filtered(user,data)); allgrades=list(filtered(user,data,True))
    total=sum((r.area for r in rows),ZERO)
    base=sum((r.area for r in allgrades),ZERO)
    first=sum((r.area for r in allgrades if r.grade.rank==1),ZERO)
    grade_map={g.pk:g for g in Grade.objects.all()}
    def grouped(records,key):
        result=defaultdict(lambda:ZERO)
        for r in records: result[key(r)]+=r.area
        return result
    def items(groups,kind):
        out=[]
        for obj,area in sorted(groups.items(),key=lambda kv:kv[1],reverse=True):
            out.append({'label':str(obj),'area':area,'share':percentage(area,total),'width':float(percentage(area,max(groups.values()) or ZERO) or 0),'color':getattr(obj,'color','#159b9a'),'url':drill(params,**{kind:obj.pk}),'id':obj.pk})
        return out
    factory_groups=grouped(rows,lambda r:r.factory)
    selected_factories=data.get('factory') or factories_for(user)
    for factory in selected_factories: factory_groups.setdefault(factory,ZERO)
    factories=items(factory_groups,'factory')
    sizes=items(grouped(rows,lambda r:r.size),'size')
    top_size=sizes[0] if sizes else None
    grades=items(grouped(rows,lambda r:r.grade),'grade')
    type_groups=grouped([r for r in rows if r.technical_type],lambda r:r.technical_type)
    designs=items(type_groups,'technical_type') if type_groups else []
    mix=grouped(allgrades,lambda r:(r.factory,r.grade))
    stacks=[]
    for f in sorted({r.factory for r in allgrades},key=lambda x:x.name):
        denom=sum((a for (fac,g),a in mix.items() if fac==f),ZERO)
        stacks.append({'label':str(f),'area':denom,'parts':[{'label':g.name,'area':mix[(f,g)],'share':percentage(mix[(f,g)],denom),'color':g.color,'url':drill(params,factory=f.pk,grade=g.pk)} for g in grade_map.values()]})
    trendkey='month' if data.get('trend')=='month' else 'day'
    dates=grouped(rows,lambda r:jalali(r.date)[:7] if trendkey=='month' else jalali(r.date))
    trend=[]
    if rows:
        start=data.get('start') or min(r.date for r in rows)
        end=data.get('end') or max(r.date for r in rows)
        # Fill zero days for bounded daily charts. Large histories use monthly series.
        if (end-start).days>120 and trendkey=='day':
            trendkey='month';dates=grouped(rows,lambda r:jalali(r.date)[:7])
        if trendkey=='day':
            for i in range((end-start).days+1): dates.setdefault(jalali(start+timedelta(days=i)),ZERO)
        maxvalue=max(dates.values()) or Decimal(1)
        for label,area in sorted(dates.items()):
            start_label=label+'/01' if trendkey=='month' else label
            if trendkey=='month':
                import jdatetime
                y,m=map(int,label.split('/')); nextdate=jdatetime.date(y+1,1,1) if m==12 else jdatetime.date(y,m+1,1)
                end_label=jalali(nextdate.togregorian()-timedelta(days=1))
            else: end_label=label
            # Keep drilldown intersected with the original bounds.
            start_label=max(start_label,jalali(start));end_label=min(end_label,jalali(end))
            trend.append({'label':label,'area':area,'height':float(area/maxvalue*100),'url':drill(params,start=start_label,end=end_label)})
    return {'rows':rows,'allgrades':allgrades,'total':total,'base_total':base,'first_share':percentage(first,base),'factories':factories,'sizes':sizes,'top_size':top_size,'grades':grades,'designs':designs,'stacks':stacks,'trend':trend,'trend_mode':trendkey,'grade_objects':list(grade_map.values())}

HEADERS={'detail':['تاریخ تولید','کارخانه','سایز','درجه','متراژ (مترمربع)','ثبت‌کننده','توضیحات'], 'day':['روز شمسی'],'month':['ماه شمسی'],'year':['سال شمسی'],'factory':['کارخانه'],'size':['سایز'],'grade':['درجه'],'type':['سایز','درجه']}

def report_table(summary,data):
    group=data.get('group') or 'detail'; records=summary['rows'];total=summary['total']
    if group=='matrix':
        grades=summary['grade_objects']
        actual=defaultdict(lambda:ZERO)
        bases=defaultdict(lambda:ZERO)
        mix=defaultdict(lambda:ZERO)
        for r in records:
            actual[(r.factory, r.size, r.grade_id)] += r.area
        for r in summary['allgrades']:
            bases[(r.factory, r.size)] += r.area
            mix[(r.factory, r.size, r.grade_id)] += r.area
        keys=sorted({(r.factory, r.size) for r in records}, key=lambda k: tuple(map(str, k)))
        headers=['کارخانه','سایز']
        for g in grades:
            headers += [g.name+' • متراژ فیلترشده', g.name+' • درصد ترکیب']
        headers += ['جمع فیلترشده','مبنای همه درجات']
        result=[]
        for key in keys:
            cells=list(map(str, key))
            for g in grades:
                cells += [actual[(*key, g.pk)], percentage(mix[(*key, g.pk)], bases[key])]
            cells += [sum((actual[(*key, g.pk)] for g in grades), ZERO), bases[key]]
            result.append({'cells': cells, 'area': cells[-2]})
        return {'headers': headers, 'body': sort_rows(result, data), 'percent_cols': list(range(4, len(headers)-2, 2)), 'area_cols': list(range(3, len(headers)-2, 2)) + [len(headers)-2, len(headers)-1], 'group': group}
    if group=='detail':
        order=data.get('order') or 'new'
        rows=sorted(records,key=lambda r: (r.area,r.id) if order.startswith('area') else (r.date,r.id),reverse=order in ('new','area_desc'))
        return {'headers':HEADERS[group],'body':[{'cells':[jalali(r.date),str(r.factory),str(r.size),str(r.grade),r.area,r.created_by.get_full_name() or r.created_by.username,r.notes],'obj':r,'area':r.area} for r in rows],'percent_cols':[],'area_cols':[4],'group':group}
    def key(r):
        return {'day':(jalali(r.date),),'month':(jalali(r.date)[:7],),'year':(jalali(r.date)[:4],),'factory':(r.factory,),'size':(r.size,),'grade':(r.grade,),'type':(r.size,r.grade)}[group]
    groups=defaultdict(lambda:ZERO)
    for r in records: groups[key(r)]+=r.area
    result=[]
    for k,area in sorted(groups.items(),key=lambda kv:tuple(str(v) for v in kv[0])):
        cells=list(map(str,k))+[area,percentage(area,total)]
        result.append({'cells':cells,'area':area})
    headers=HEADERS[group]+['متراژ (مترمربع)','سهم از نتایج فیلترشده ٪']
    return {'headers':headers,'body':sort_rows(result,data),'percent_cols':list(range(len(HEADERS[group])+1,len(headers))),'area_cols':[len(HEADERS[group])],'group':group}

def sort_rows(rows,data):
    order=data.get('order') or 'new'
    if order.startswith('area'): return sorted(rows,key=lambda r:r['area'],reverse=order=='area_desc')
    return sorted(rows,key=lambda r:tuple(str(c) for c in r['cells'][:1]),reverse=order=='new')
