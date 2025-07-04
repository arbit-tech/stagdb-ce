from django.db import models
from django.contrib.auth.models import User


class HostVM(models.Model):
    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    username = models.CharField(max_length=50)
    ssh_key = models.TextField(blank=True)
    password = models.CharField(max_length=255, blank=True)
    zfs_pool = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.ip_address})"


class Database(models.Model):
    name = models.CharField(max_length=100)
    host_vm = models.ForeignKey(HostVM, on_delete=models.CASCADE)
    db_type = models.CharField(max_length=50, default='postgresql')
    db_version = models.CharField(max_length=20, default='15')
    container_name = models.CharField(max_length=100, unique=True)
    zfs_dataset = models.CharField(max_length=200)
    port = models.IntegerField()
    username = models.CharField(max_length=50, default='postgres')
    password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} on {self.host_vm.name}"


class DatabaseBranch(models.Model):
    database = models.ForeignKey(Database, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    snapshot_name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['database', 'name']
    
    def __str__(self):
        return f"{self.database.name}:{self.name}"