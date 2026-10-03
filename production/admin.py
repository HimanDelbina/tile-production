from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Factory, Size, Grade, Profile, Production, Audit, Submission

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

# Register models with default admin to allow add, change, delete
admin.site.register(Factory)
admin.site.register(Size)
admin.site.register(Grade)
admin.site.register(Profile)
admin.site.register(Production)
admin.site.register(Audit)
admin.site.register(Submission)
