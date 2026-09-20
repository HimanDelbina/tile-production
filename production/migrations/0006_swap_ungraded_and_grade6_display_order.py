from django.db import migrations


DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def compact(value):
    return ''.join(str(value).translate(DIGITS).lower().replace('\u200c', '').split()).replace('-', '').replace('_', '')


def find_pair(Grade):
    grade_6 = ungraded = None
    for grade in Grade.objects.all():
        name = compact(grade.name)
        if name in {'درجه6', 'grade6', 'g6'}:
            grade_6 = grade
        elif name in {'آنگرید', 'انگرید', 'ungrade', 'ungraded'}:
            ungraded = grade
    return grade_6, ungraded


def put_ungraded_before_grade_6(apps, schema_editor):
    Grade = apps.get_model('production', 'Grade')
    grade_6, ungraded = find_pair(Grade)
    if not grade_6 or not ungraded or ungraded.rank < grade_6.rank:
        return
    old_grade_6_rank, old_ungraded_rank = grade_6.rank, ungraded.rank
    temporary_rank = max(Grade.objects.values_list('rank', flat=True), default=0) + 1
    grade_6.rank = temporary_rank
    grade_6.save(update_fields=['rank'])
    ungraded.rank = old_grade_6_rank
    ungraded.save(update_fields=['rank'])
    grade_6.rank = old_ungraded_rank
    grade_6.save(update_fields=['rank'])


def restore_grade_6_before_ungraded(apps, schema_editor):
    Grade = apps.get_model('production', 'Grade')
    grade_6, ungraded = find_pair(Grade)
    if not grade_6 or not ungraded or grade_6.rank < ungraded.rank:
        return
    old_grade_6_rank, old_ungraded_rank = grade_6.rank, ungraded.rank
    temporary_rank = max(Grade.objects.values_list('rank', flat=True), default=0) + 1
    ungraded.rank = temporary_rank
    ungraded.save(update_fields=['rank'])
    grade_6.rank = old_ungraded_rank
    grade_6.save(update_fields=['rank'])
    ungraded.rank = old_grade_6_rank
    ungraded.save(update_fields=['rank'])


class Migration(migrations.Migration):
    dependencies = [('production', '0005_productionimportrow_source_errors_and_more')]
    operations = [migrations.RunPython(put_ungraded_before_grade_6, restore_grade_6_before_ungraded)]
