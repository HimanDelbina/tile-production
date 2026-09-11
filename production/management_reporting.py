from decimal import Decimal
from collections import defaultdict
import re
from django.db.models import Sum
from django.http import QueryDict

from .models import Factory, Grade, Size, Production
from .permissions import factories_for
from .dates import jalali, normalize

ZERO = Decimal('0')

def is_first_grade(grade_obj_or_name):
    if not grade_obj_or_name:
        return False
    name_str = getattr(grade_obj_or_name, 'name', str(grade_obj_or_name))
    norm = normalize(name_str).lower().strip()
    compact = re.sub(r'[\s\u200c\-_]+', '', norm)
    if compact in ('درجه1', 'grade1', 'درجهیک', 'درجهاول', 'g1', 'gradeone', 'یک', '1'):
        return True
    if re.search(r'(?:درجه|grade)\s*(?:1|یک|اول|one)\b', norm):
        return True
    return False

def calc_percentage(numerator, denominator):
    if not denominator or denominator == ZERO:
        return None
    if not numerator or numerator == ZERO:
        return Decimal('0.00')
    return (numerator / denominator) * 100

def get_management_report_data(user, cleaned_data, query_params):
    permitted_factories = list(factories_for(user).order_by('name'))
    permitted_factory_ids = {f.pk for f in permitted_factories}

    if cleaned_data.get('factory'):
        selected_factories = [f for f in cleaned_data['factory'] if f.pk in permitted_factory_ids]
        if not selected_factories:
            selected_factories = permitted_factories
    else:
        selected_factories = permitted_factories

    selected_factory_ids = [f.pk for f in selected_factories]

    qs = Production.objects.filter(
        deleted_at__isnull=True,
        factory_id__in=selected_factory_ids
    )

    if cleaned_data.get('start'):
        qs = qs.filter(date__gte=cleaned_data['start'])
    if cleaned_data.get('end'):
        qs = qs.filter(date__lte=cleaned_data['end'])
    if cleaned_data.get('size'):
        qs = qs.filter(size__in=cleaned_data['size'])

    # Single aggregation query
    aggregated_data = list(qs.values('factory_id', 'size_id', 'grade_id').annotate(total_area=Sum('area')))

    # All grades in the system, preserving order of rank then id
    db_grades = list(Grade.objects.all().order_by('rank', 'id'))
    grade_map = {g.pk: g for g in db_grades}

    # Sizes
    db_sizes = list(Size.objects.all().order_by('width', 'length'))
    size_map = {s.pk: s for s in db_sizes}

    matrix = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: ZERO)))
    factory_size_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    factory_grade_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    factory_totals = defaultdict(lambda: ZERO)

    aggregated_size_grade_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    aggregated_size_totals = defaultdict(lambda: ZERO)
    aggregated_grade_totals = defaultdict(lambda: ZERO)

    overall_total_area = ZERO
    first_grade_total_area = ZERO

    active_size_ids_per_factory = defaultdict(set)
    all_active_size_ids = set()

    for item in aggregated_data:
        f_id = item['factory_id']
        s_id = item['size_id']
        g_id = item['grade_id']
        area = item['total_area'] or ZERO

        matrix[f_id][s_id][g_id] += area
        factory_size_totals[f_id][s_id] += area
        factory_grade_totals[f_id][g_id] += area
        factory_totals[f_id] += area

        aggregated_size_grade_totals[s_id][g_id] += area
        aggregated_size_totals[s_id] += area
        aggregated_grade_totals[g_id] += area

        overall_total_area += area

        active_size_ids_per_factory[f_id].add(s_id)
        all_active_size_ids.add(s_id)

    factory_first_grade_totals = defaultdict(lambda: ZERO)
    for g in db_grades:
        if is_first_grade(g):
            first_grade_total_area += aggregated_grade_totals[g.pk]
            for f in selected_factories:
                factory_first_grade_totals[f.pk] += factory_grade_totals[f.pk][g.pk]

    def make_drill_url(**kwargs):
        p = query_params.copy() if query_params else QueryDict('', mutable=True)
        if not hasattr(p, 'mutable') or not p.mutable:
            p = p.copy()
        for k, v in kwargs.items():
            if v is None:
                p.pop(k, None)
            elif isinstance(v, (list, tuple, set)):
                p.setlist(k, [str(x) for x in v])
            else:
                p[k] = str(v)
        p['group'] = 'detail'
        p.pop('page', None)
        return '/reports/?' + p.urlencode()

    first_grade_pct = calc_percentage(first_grade_total_area, overall_total_area)
    producing_factories_count = sum(1 for f in selected_factories if factory_totals[f.pk] > ZERO)
    producing_sizes_count = len(all_active_size_ids)

    summary_cards = {
        'total_area': overall_total_area,
        'first_grade_area': first_grade_total_area,
        'first_grade_percentage': first_grade_pct,
        'producing_factories_count': producing_factories_count,
        'producing_sizes_count': producing_sizes_count,
        'url': make_drill_url()
    }

    factory_cards = []
    for f in selected_factories:
        f_area = factory_totals[f.pk]
        f_share = calc_percentage(f_area, overall_total_area)
        f_first_area = factory_first_grade_totals[f.pk]
        f_first_pct = calc_percentage(f_first_area, f_area)
        has_prod = f_area > ZERO

        factory_cards.append({
            'factory': f,
            'name': f.name,
            'total_area': f_area,
            'share_of_total': f_share,
            'first_grade_area': f_first_area,
            'first_grade_percentage': f_first_pct,
            'has_production': has_prod,
            'url': make_drill_url(factory=f.pk)
        })

    max_f_area = max([fc['total_area'] for fc in factory_cards], default=ZERO) or Decimal(1)
    factory_comparison_chart = []
    for fc in factory_cards:
        factory_comparison_chart.append({
            'factory': fc['factory'],
            'name': fc['name'],
            'area': fc['total_area'],
            'share': fc['share_of_total'],
            'bar_width': float(fc['total_area'] / max_f_area * 100) if max_f_area > ZERO else 0,
            'url': fc['url'],
            'has_production': fc['has_production']
        })

    factory_grade_mix_chart = []
    for f in selected_factories:
        f_area = factory_totals[f.pk]
        if f_area > ZERO:
            parts = []
            for g in db_grades:
                g_area = factory_grade_totals[f.pk][g.pk]
                if g_area > ZERO:
                    share = (g_area / f_area) * 100
                    parts.append({
                        'grade': g,
                        'label': g.name,
                        'area': g_area,
                        'share': share,
                        'color': g.color,
                        'url': make_drill_url(factory=f.pk, grade=g.pk)
                    })
            factory_grade_mix_chart.append({
                'factory': f,
                'name': f.name,
                'total_area': f_area,
                'parts': parts,
                'has_production': True
            })
        else:
            factory_grade_mix_chart.append({
                'factory': f,
                'name': f.name,
                'total_area': ZERO,
                'parts': [],
                'has_production': False
            })

    requested_sizes = list(cleaned_data['size']) if cleaned_data.get('size') else None

    factory_tables = []
    for f in selected_factories:
        f_area = factory_totals[f.pk]
        if requested_sizes:
            f_sizes = [s for s in requested_sizes if s.pk in size_map]
        else:
            f_sizes = [size_map[sid] for sid in sorted(active_size_ids_per_factory[f.pk], key=lambda x: (size_map[x].width, size_map[x].length)) if sid in size_map]

        table_rows = []
        for s in f_sizes:
            s_area = factory_size_totals[f.pk][s.pk]
            s_share = calc_percentage(s_area, f_area)

            grade_cells = []
            for g in db_grades:
                g_area = matrix[f.pk][s.pk][g.pk]
                g_pct = calc_percentage(g_area, s_area)
                grade_cells.append({
                    'grade': g,
                    'area': g_area,
                    'percentage': g_pct,
                    'url': make_drill_url(factory=f.pk, size=s.pk, grade=g.pk)
                })

            table_rows.append({
                'size': s,
                'size_label': str(s),
                'total_area': s_area,
                'share_of_factory': s_share,
                'grades': grade_cells,
                'url': make_drill_url(factory=f.pk, size=s.pk)
            })

        footer_grades = []
        for g in db_grades:
            g_total = factory_grade_totals[f.pk][g.pk]
            g_pct = calc_percentage(g_total, f_area)
            footer_grades.append({
                'grade': g,
                'area': g_total,
                'percentage': g_pct,
                'url': make_drill_url(factory=f.pk, grade=g.pk)
            })

        factory_tables.append({
            'factory': f,
            'name': f.name,
            'total_area': f_area,
            'has_production': f_area > ZERO,
            'rows': table_rows,
            'footer': {
                'label': 'جمع کل',
                'total_area': f_area,
                'share_of_factory': Decimal('100.00') if f_area > ZERO else None,
                'grades': footer_grades,
                'url': make_drill_url(factory=f.pk)
            }
        })

    if requested_sizes:
        agg_sizes = [s for s in requested_sizes if s.pk in size_map]
    else:
        agg_sizes = [size_map[sid] for sid in sorted(all_active_size_ids, key=lambda x: (size_map[x].width, size_map[x].length)) if sid in size_map]

    agg_table_rows = []
    selected_factory_pks = [f.pk for f in selected_factories] if len(selected_factories) < len(permitted_factories) else None

    for s in agg_sizes:
        s_total = aggregated_size_totals[s.pk]
        s_share = calc_percentage(s_total, overall_total_area)

        grade_cells = []
        for g in db_grades:
            g_area = aggregated_size_grade_totals[s.pk][g.pk]
            g_pct = calc_percentage(g_area, s_total)
            grade_cells.append({
                'grade': g,
                'area': g_area,
                'percentage': g_pct,
                'url': make_drill_url(size=s.pk, grade=g.pk, factory=selected_factory_pks)
            })

        agg_table_rows.append({
            'size': s,
            'size_label': str(s),
            'total_area': s_total,
            'share_of_total': s_share,
            'grades': grade_cells,
            'url': make_drill_url(size=s.pk, factory=selected_factory_pks)
        })

    agg_footer_grades = []
    for g in db_grades:
        g_total = aggregated_grade_totals[g.pk]
        g_pct = calc_percentage(g_total, overall_total_area)
        agg_footer_grades.append({
            'grade': g,
            'area': g_total,
            'percentage': g_pct,
            'url': make_drill_url(grade=g.pk, factory=selected_factory_pks)
        })

    aggregated_table = {
        'title': 'جمع تولید کارخانه‌های انتخاب‌شده به تفکیک سایز',
        'has_production': overall_total_area > ZERO,
        'rows': agg_table_rows,
        'footer': {
            'label': 'جمع کل',
            'total_area': overall_total_area,
            'share_of_total': Decimal('100.00') if overall_total_area > ZERO else None,
            'grades': agg_footer_grades,
            'url': make_drill_url(factory=selected_factory_pks)
        }
    }

    return {
        'summary_cards': summary_cards,
        'factory_cards': factory_cards,
        'factory_comparison_chart': factory_comparison_chart,
        'factory_grade_mix_chart': factory_grade_mix_chart,
        'factory_tables': factory_tables,
        'aggregated_table': aggregated_table,
        'grades': db_grades,
        'selected_factories': selected_factories,
        'permitted_factories': permitted_factories,
        'all_selected': len(selected_factories) == len(permitted_factories),
    }
