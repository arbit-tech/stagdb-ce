from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import HostVM, Database


def health_check(request):
    return JsonResponse({'status': 'healthy'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def vm_list(request):
    vms = HostVM.objects.filter(is_active=True)
    data = [{
        'id': vm.id,
        'name': vm.name,
        'ip_address': vm.ip_address,
        'username': vm.username,
        'zfs_pool': vm.zfs_pool,
        'created_at': vm.created_at
    } for vm in vms]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def database_list(request):
    databases = Database.objects.filter(is_active=True)
    data = [{
        'id': db.id,
        'name': db.name,
        'host_vm': db.host_vm.name,
        'db_type': db.db_type,
        'db_version': db.db_version,
        'port': db.port,
        'created_at': db.created_at
    } for db in databases]
    return Response(data)