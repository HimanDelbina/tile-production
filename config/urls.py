from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path
from production import views
urlpatterns=[path('admin/',admin.site.urls),path('login/',auth.LoginView.as_view(template_name='registration/login.html'),name='login'),path('logout/',auth.LogoutView.as_view(),name='logout'),path('password/',auth.PasswordChangeView.as_view(template_name='registration/password.html',success_url='/'),name='password'),path('',views.management_report,name='management_report'),path('overview/',views.dashboard,name='dashboard'),path('reports/',views.reports,name='reports'),path('production/new/',views.create,name='create'),path('production/<int:pk>/edit/',views.edit,name='edit'),path('production/<int:pk>/delete/',views.delete,name='delete'),path('production/<int:pk>/history/',views.history,name='history'),path('master/<str:kind>/',views.master,name='master'),path('master/<str:kind>/<int:pk>/',views.master,name='master_edit'),path('users/',views.users,name='users'),path('users/<int:pk>/',views.users,name='user_edit'),path('calendar/',views.calendar_month,name='calendar'),path('export/<str:kind>/',views.export,name='export'),path('health/',views.health,name='health'),path('import/',views.import_upload,name='import_upload'),path('import/preview/<uuid:token>/',views.import_preview,name='import_preview'),path('import/confirm/<uuid:token>/',views.import_confirm,name='import_confirm'),path('import/download/<uuid:token>/',views.import_file_download,name='import_file_download'),]
admin.site.site_header='مدیریت فنی سامانه تولید'
urlpatterns += [
    path('management-preview/', views.management_report, {'template_name': 'production/management_report.html'}, name='management_preview'),
    path('management-report/', views.management_report, {'template_name': 'production/management_report.html'}, name='management_detailed'),
]
admin.site.site_title='مدیریت فنی'
