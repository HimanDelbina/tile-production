from django.contrib import admin
from .models import Factory, Size, Grade, Profile, Production, Audit, Submission

# Register models with default admin to allow add, change, delete
admin.site.register(Factory)
admin.site.register(Size)
admin.site.register(Grade)
admin.site.register(Profile)
admin.site.register(Production)
admin.site.register(Audit)
admin.site.register(Submission)
