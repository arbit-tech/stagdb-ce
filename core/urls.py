from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health_check, name='health'),
    path('vms/', views.vm_list, name='vm_list'),
    path('databases/', views.database_list, name='database_list'),
]