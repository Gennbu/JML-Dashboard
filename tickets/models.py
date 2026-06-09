from django.db import models

class Ticket(models.Model):
    request_id = models.CharField(max_length=50, unique=True)
    subject = models.CharField(max_length=500)
    request_status = models.CharField(max_length=100)
    technician = models.CharField(max_length=200, blank=True, null=True)
    created_time = models.DateTimeField(null=True, blank=True)
    last_updated =  models.DateTimeField(blank=True, null=True)
    linked_request_id = models.CharField(max_length=50, blank=True, null=True)
    requester = models.CharField(max_length=200, blank=True, null=True)
    resolved_time = models.DateField(blank=True, null=True)
    
    def __str__(self):
        return self.request_id
        
        
