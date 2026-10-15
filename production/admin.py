from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Factory, Size, Grade, Glaze, Profile, Production, Audit, Submission, TechnicalType, ProductionImportBatch, ProductionImportRow

User = get_user_model()

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name = 'پروفایل و دسترسی‌های سامانه تولید'
    verbose_name_plural = 'پروفایل و دسترسی‌های سامانه تولید'
    filter_horizontal = ('factories',)

class CustomUserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, CustomUserAdmin)

class ProductionImportRowInline(admin.TabularInline):
    model = ProductionImportRow
    extra = 0
    fields = ('excel_row', 'raw_description', 'area', 'size', 'glaze', 'grade', 'technical_type', 'status', 'error_message')
    readonly_fields = ('excel_row', 'raw_description')

@admin.register(ProductionImportBatch)
class ProductionImportBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'factory', 'date', 'uploaded_by', 'uploaded_at', 'status', 'confirmed_at', 'sheet_name')
    list_filter = ('status', 'factory', 'date')
    search_fields = ('factory__name', 'file_hash', 'sheet_name')
    readonly_fields = ('token', 'file_hash', 'uploaded_at')
    inlines = [ProductionImportRowInline]

# Register models with default admin to allow add, change, delete
admin.site.register(Factory)
admin.site.register(Size)
admin.site.register(Grade)
admin.site.register(Glaze)
admin.site.register(Profile)
admin.site.register(Production)
admin.site.register(Audit)
admin.site.register(Submission)
admin.site.register(TechnicalType)
