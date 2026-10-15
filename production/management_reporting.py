from decimal import Decimal
from collections import defaultdict
import re
from django.db.models import Sum
from django.http import QueryDict

from .models import Factory, Grade, Size, Glaze, TechnicalType, Production
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

def format_product_label(size_obj, glaze_obj, tech_obj) -> str:
    parts = []
    if size_obj:
        parts.append(str(size_obj))
    else:
        parts.append('بدون سایز')
    if glaze_obj and glaze_obj.name:
        parts.append(glaze_obj.name.strip())
    if tech_obj and tech_obj.name:
        t_name = tech_obj.name.strip()
        m = re.match(r'^([\d\.]+)\s*(?:mil|میل|میلیمتر|میلی\s*متر|mm)?$', t_name, re.IGNORECASE)
        parts.append(f"{m.group(1)} میل" if m else t_name)
    return " ".join(parts)

def product_sort_key(prod_key, size_map, glaze_map, tech_map):
    s_id, gz_id, tt_id = prod_key
    size = size_map.get(s_id)
    size_sort = (size.width, size.length) if size else (9999, 9999)
    glaze = glaze_map.get(gz_id)
    glaze_sort = (0, glaze.name) if (glaze and glaze.name) else (1, '')
    tech = tech_map.get(tt_id)
    if tech and tech.name:
        m = re.match(r'^([\d\.]+)', tech.name.strip())
        tech_val = float(m.group(1)) if m else 999.0
        tech_sort = (0, tech_val, tech.name)
    else:
        tech_sort = (1, 999.0, '')
    return (size_sort, glaze_sort, tech_sort, s_id or 0, gz_id or 0, tt_id or 0)

def get_management_report_data(user, cleaned_data, query_params, *, sample_dates=None, include_days=False, product_rows=None):
    if product_rows is None:
        product_rows = include_days
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
    if cleaned_data.get('glaze'):
        qs = qs.filter(glaze__in=cleaned_data['glaze'])
    if cleaned_data.get('technical_type'):
        qs = qs.filter(technical_type__in=cleaned_data['technical_type'])

    # Single aggregation query
    group_fields = ['factory_id', 'size_id', 'glaze_id', 'technical_type_id', 'grade_id']
    if include_days:
        group_fields.append('date')
    aggregated_data = list(qs.values(*group_fields).annotate(total_area=Sum('area'))) if sample_dates is None else []

    # All active grades in the system, preserving order of rank then id
    db_grades = list(Grade.objects.filter(active=True).order_by('rank', 'id'))
    grade_map = {g.pk: g for g in db_grades}

    # Sizes
    db_sizes = list(Size.objects.filter(active=True).order_by('width', 'length'))
    size_map = {s.pk: s for s in db_sizes}

    # Glazes
    db_glazes = list(Glaze.objects.filter(active=True).order_by('name', 'id'))
    glaze_map = {g.pk: g for g in db_glazes}

    # Preview-only rows in memory: never create or update production records.
    if sample_dates is not None:
        db_techs = list(TechnicalType.objects.all())
        sample_tech = db_techs[0] if db_techs else None
        sample_dates = sorted(set(sample_dates))
        sample_sizes = db_sizes[:2]
        sample_glazes = db_glazes[:3] if db_glazes else [None]
        if cleaned_data.get('size'):
            selected_size_ids = {s.pk for s in cleaned_data['size']}
            sample_sizes = [s for s in sample_sizes if s.pk in selected_size_ids]
        if cleaned_data.get('glaze'):
            selected_glaze_ids = {g.pk for g in cleaned_data['glaze']}
            sample_glazes = [g for g in sample_glazes if g and g.pk in selected_glaze_ids]
        for sample_date in sample_dates:
            if cleaned_data.get('start') and sample_date < cleaned_data['start']:
                continue
            if cleaned_data.get('end') and sample_date > cleaned_data['end']:
                continue
            day_factor = Decimal('1') if sample_date == sample_dates[-1] else Decimal('0.85')
            for factory in selected_factories:
                for size in sample_sizes:
                    for g_idx, glaze in enumerate(sample_glazes):
                        glaze_factor = Decimal('1') if not db_glazes else (Decimal('0.5') if g_idx == 0 else Decimal('0.25'))
                        base = Decimal(4200 + factory.pk % 5 * 600 + size.pk % 3 * 350) * day_factor * glaze_factor
                        for index, grade in enumerate(db_grades):
                            weight = Decimal('0.76') if is_first_grade(grade) else Decimal('0.18') / Decimal(index + 1)
                            aggregated_data.append({
                                'date': sample_date,
                                'factory_id': factory.pk, 'size_id': size.pk,
                                'glaze_id': glaze.pk if glaze else None,
                                'technical_type_id': sample_tech.pk if sample_tech else None,
                                'grade_id': grade.pk,
                                'total_area': (base * weight).quantize(Decimal('0.01')),
                            })

    report = _build_management_report(permitted_factories, selected_factories, db_grades, db_sizes, db_glazes, cleaned_data, query_params, aggregated_data, product_rows=product_rows)
    if include_days:
        rows_by_date = defaultdict(list)
        for row in aggregated_data:
            rows_by_date[row['date']].append(row)
        report['daily_reports'] = []
        for day, rows in sorted(rows_by_date.items()):
            day_data = {**cleaned_data, 'start': day, 'end': day}
            day_params = query_params.copy()
            day_params['start'] = jalali(day)
            day_params['end'] = jalali(day)
            day_report = _build_management_report(permitted_factories, selected_factories, db_grades, db_sizes, db_glazes, day_data, day_params, rows, product_rows=product_rows)
            report['daily_reports'].append({'date': day, 'report': day_report})
    return report


def _build_management_report(permitted_factories, selected_factories, db_grades, db_sizes, db_glazes, cleaned_data, query_params, aggregated_data, product_rows=False):
    size_map = {s.pk: s for s in db_sizes}
    glaze_map = {g.pk: g for g in db_glazes}
    matrix = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: ZERO)))
    factory_size_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    factory_grade_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    factory_totals = defaultdict(lambda: ZERO)

    db_techs = list(TechnicalType.objects.all())
    tech_map = {t.pk: t for t in db_techs}

    factory_prod_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    factory_prod_grade = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: ZERO)))
    active_products_per_factory = defaultdict(set)

    aggregated_prod_totals = defaultdict(lambda: ZERO)
    aggregated_prod_grade = defaultdict(lambda: defaultdict(lambda: ZERO))
    all_active_products = set()

    factory_size_glaze_totals = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: ZERO)))
    factory_size_glaze_grade = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: ZERO))))
    factory_size_glaze_techs = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    active_glaze_ids_per_factory_size = defaultdict(lambda: defaultdict(set))

    aggregated_size_grade_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    aggregated_size_totals = defaultdict(lambda: ZERO)
    aggregated_size_glaze_totals = defaultdict(lambda: defaultdict(lambda: ZERO))
    aggregated_size_glaze_grade = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: ZERO)))
    aggregated_size_glaze_techs = defaultdict(lambda: defaultdict(set))
    all_active_glaze_ids_per_size = defaultdict(set)
    aggregated_grade_totals = defaultdict(lambda: ZERO)

    overall_total_area = ZERO
    first_grade_total_area = ZERO

    active_size_ids_per_factory = defaultdict(set)
    all_active_size_ids = set()

    for item in aggregated_data:
        f_id = item['factory_id']
        s_id = item['size_id']
        gz_id = item.get('glaze_id')
        tt_id = item.get('technical_type_id')
        g_id = item['grade_id']
        area = item['total_area'] or ZERO

        matrix[f_id][s_id][g_id] += area
        factory_size_totals[f_id][s_id] += area
        factory_grade_totals[f_id][g_id] += area
        factory_totals[f_id] += area

        prod_key = (s_id, gz_id, tt_id)
        factory_prod_totals[f_id][prod_key] += area
        factory_prod_grade[f_id][prod_key][g_id] += area
        if area > ZERO or gz_id is not None or tt_id is not None:
            active_products_per_factory[f_id].add(prod_key)
            all_active_products.add(prod_key)

        aggregated_prod_totals[prod_key] += area
        aggregated_prod_grade[prod_key][g_id] += area

        factory_size_glaze_totals[f_id][s_id][gz_id] += area
        factory_size_glaze_grade[f_id][s_id][gz_id][g_id] += area
        if tt_id:
            factory_size_glaze_techs[f_id][s_id][gz_id].add(tt_id)
            aggregated_size_glaze_techs[s_id][gz_id].add(tt_id)

        if area > ZERO or gz_id is not None:
            active_glaze_ids_per_factory_size[f_id][s_id].add(gz_id)
            all_active_glaze_ids_per_size[s_id].add(gz_id)

        aggregated_size_grade_totals[s_id][g_id] += area
        aggregated_size_totals[s_id] += area
        aggregated_size_glaze_totals[s_id][gz_id] += area
        aggregated_size_glaze_grade[s_id][gz_id][g_id] += area
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

    if product_rows:
        factory_tables = []
        for f in selected_factories:
            f_area = factory_totals[f.pk]
            f_prod_keys = [pk for pk in active_products_per_factory[f.pk] if pk[0] in size_map]
            if cleaned_data.get('size'):
                req_size_ids = {s.pk for s in cleaned_data['size']}
                f_prod_keys = [pk for pk in f_prod_keys if pk[0] in req_size_ids]
            if cleaned_data.get('glaze'):
                req_glaze_ids = {g.pk for g in cleaned_data['glaze']}
                f_prod_keys = [pk for pk in f_prod_keys if pk[1] in req_glaze_ids]
            if cleaned_data.get('technical_type'):
                req_tt_ids = {t.pk for t in cleaned_data['technical_type']}
                f_prod_keys = [pk for pk in f_prod_keys if pk[2] in req_tt_ids]

            f_prod_keys.sort(key=lambda pk: product_sort_key(pk, size_map, glaze_map, tech_map))

            table_rows = []
            for prod_key in f_prod_keys:
                s_id, gz_id, tt_id = prod_key
                s = size_map.get(s_id)
                gz_obj = glaze_map.get(gz_id)
                tt_obj = tech_map.get(tt_id)
                prod_area = factory_prod_totals[f.pk][prod_key]
                prod_share = calc_percentage(prod_area, f_area)

                grade_cells = []
                for g in db_grades:
                    g_area = factory_prod_grade[f.pk][prod_key][g.pk]
                    g_pct = calc_percentage(g_area, prod_area)
                    grade_cells.append({
                        'grade': g,
                        'area': g_area,
                        'percentage': g_pct,
                        'url': make_drill_url(
                            factory=f.pk,
                            size=s_id,
                            glaze=gz_id if gz_id else None,
                            technical_type=tt_id if tt_id else None,
                            grade=g.pk
                        )
                    })

                table_rows.append({
                    'size': s,
                    'glaze': gz_obj,
                    'technical_type': tt_obj,
                    'size_label': format_product_label(s, gz_obj, tt_obj),
                    'total_area': prod_area,
                    'share_of_factory': prod_share,
                    'grades': grade_cells,
                    'glazes': [],
                    'url': make_drill_url(
                        factory=f.pk,
                        size=s_id,
                        glaze=gz_id if gz_id else None,
                        technical_type=tt_id if tt_id else None
                    )
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

        selected_factory_pks = [f.pk for f in selected_factories] if len(selected_factories) < len(permitted_factories) else None
        agg_prod_keys = [pk for pk in all_active_products if pk[0] in size_map]
        if cleaned_data.get('size'):
            req_size_ids = {s.pk for s in cleaned_data['size']}
            agg_prod_keys = [pk for pk in agg_prod_keys if pk[0] in req_size_ids]
        if cleaned_data.get('glaze'):
            req_glaze_ids = {g.pk for g in cleaned_data['glaze']}
            agg_prod_keys = [pk for pk in agg_prod_keys if pk[1] in req_glaze_ids]
        if cleaned_data.get('technical_type'):
            req_tt_ids = {t.pk for t in cleaned_data['technical_type']}
            agg_prod_keys = [pk for pk in agg_prod_keys if pk[2] in req_tt_ids]

        agg_prod_keys.sort(key=lambda pk: product_sort_key(pk, size_map, glaze_map, tech_map))

        agg_table_rows = []
        for prod_key in agg_prod_keys:
            s_id, gz_id, tt_id = prod_key
            s = size_map.get(s_id)
            gz_obj = glaze_map.get(gz_id)
            tt_obj = tech_map.get(tt_id)
            prod_total = aggregated_prod_totals[prod_key]
            prod_share = calc_percentage(prod_total, overall_total_area)

            grade_cells = []
            for g in db_grades:
                g_area = aggregated_prod_grade[prod_key][g.pk]
                g_pct = calc_percentage(g_area, prod_total)
                grade_cells.append({
                    'grade': g,
                    'area': g_area,
                    'percentage': g_pct,
                    'url': make_drill_url(
                        size=s_id,
                        glaze=gz_id if gz_id else None,
                        technical_type=tt_id if tt_id else None,
                        grade=g.pk,
                        factory=selected_factory_pks
                    )
                })

            agg_table_rows.append({
                'size': s,
                'glaze': gz_obj,
                'technical_type': tt_obj,
                'size_label': format_product_label(s, gz_obj, tt_obj),
                'total_area': prod_total,
                'share_of_total': prod_share,
                'grades': grade_cells,
                'glazes': [],
                'url': make_drill_url(
                    size=s_id,
                    glaze=gz_id if gz_id else None,
                    technical_type=tt_id if tt_id else None,
                    factory=selected_factory_pks
                )
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
            'title': 'جمع کل بازه · همهٔ روزها و کارخانه‌های انتخاب‌شده',
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
    else:
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

                active_gz_ids = active_glaze_ids_per_factory_size[f.pk][s.pk]
                sorted_gz_ids = sorted(active_gz_ids, key=lambda x: (0, glaze_map[x].name) if (x and x in glaze_map) else (1, ''))
                glaze_rows = []
                for gz_id in sorted_gz_ids:
                    gz_obj = glaze_map.get(gz_id)
                    gz_label = gz_obj.name if gz_obj else 'بدون لعاب'
                    gz_area = factory_size_glaze_totals[f.pk][s.pk][gz_id]
                    gz_share_of_size = calc_percentage(gz_area, s_area)
                    gz_share_of_factory = calc_percentage(gz_area, f_area)

                    gz_grades = []
                    for g in db_grades:
                        g_area = factory_size_glaze_grade[f.pk][s.pk][gz_id][g.pk]
                        g_pct = calc_percentage(g_area, gz_area)
                        gz_grades.append({
                            'grade': g,
                            'area': g_area,
                            'percentage': g_pct,
                            'url': make_drill_url(factory=f.pk, size=s.pk, glaze=gz_id if gz_id else None, grade=g.pk)
                        })

                    tech_ids = factory_size_glaze_techs[f.pk][s.pk][gz_id]
                    tech_names = sorted([tech_map[tid].name for tid in tech_ids if tid in tech_map])
                    thickness_label = "، ".join(tech_names) if tech_names else ""

                    glaze_rows.append({
                        'glaze': gz_obj,
                        'glaze_label': gz_label,
                        'thickness_label': thickness_label,
                        'total_area': gz_area,
                        'share_of_size': gz_share_of_size,
                        'share_of_factory': gz_share_of_factory,
                        'grades': gz_grades,
                        'url': make_drill_url(factory=f.pk, size=s.pk, glaze=gz_id if gz_id else None)
                    })

                table_rows.append({
                    'size': s,
                    'size_label': str(s),
                    'total_area': s_area,
                    'share_of_factory': s_share,
                    'grades': grade_cells,
                    'glazes': glaze_rows,
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

            active_gz_ids = all_active_glaze_ids_per_size[s.pk]
            sorted_gz_ids = sorted(active_gz_ids, key=lambda x: (0, glaze_map[x].name) if (x and x in glaze_map) else (1, ''))
            agg_glaze_rows = []
            for gz_id in sorted_gz_ids:
                gz_obj = glaze_map.get(gz_id)
                gz_label = gz_obj.name if gz_obj else 'بدون لعاب'
                gz_area = aggregated_size_glaze_totals[s.pk][gz_id]
                gz_share_of_size = calc_percentage(gz_area, s_total)
                gz_share_of_total = calc_percentage(gz_area, overall_total_area)

                gz_grades = []
                for g in db_grades:
                    g_area = aggregated_size_glaze_grade[s.pk][gz_id][g.pk]
                    g_pct = calc_percentage(g_area, gz_area)
                    gz_grades.append({
                        'grade': g,
                        'area': g_area,
                        'percentage': g_pct,
                        'url': make_drill_url(size=s.pk, glaze=gz_id if gz_id else None, grade=g.pk, factory=selected_factory_pks)
                    })

                tech_ids = aggregated_size_glaze_techs[s.pk][gz_id]
                tech_names = sorted([tech_map[tid].name for tid in tech_ids if tid in tech_map])
                thickness_label = "، ".join(tech_names) if tech_names else ""

                agg_glaze_rows.append({
                    'glaze': gz_obj,
                    'glaze_label': gz_label,
                    'thickness_label': thickness_label,
                    'total_area': gz_area,
                    'share_of_size': gz_share_of_size,
                    'share_of_total': gz_share_of_total,
                    'grades': gz_grades,
                    'url': make_drill_url(size=s.pk, glaze=gz_id if gz_id else None, factory=selected_factory_pks)
                })

            agg_table_rows.append({
                'size': s,
                'size_label': str(s),
                'total_area': s_total,
                'share_of_total': s_share,
                'grades': grade_cells,
                'glazes': agg_glaze_rows,
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
        'glazes': db_glazes,
        'selected_factories': selected_factories,
        'permitted_factories': permitted_factories,
        'all_selected': len(selected_factories) == len(permitted_factories),
    }
