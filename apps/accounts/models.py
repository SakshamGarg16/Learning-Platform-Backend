import uuid
from django.db import models


class Learner(models.Model):
    MODE_CHOICES = (
        ('ELITE', 'Elite'),
        ('SCALE', 'Scale'),
    )
    EXPERIENCE_CHOICES = (
        ('student', 'Student'),
        ('professional', 'Professional'),
        ('switcher', 'Switcher'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    auth_user_id = models.CharField(max_length=255, unique=True, help_text="ID from OIDC/Authentik")
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='SCALE')
    experience_level = models.CharField(max_length=20, choices=EXPERIENCE_CHOICES, default='student')
    
    timezone = models.CharField(max_length=100, default='UTC')
    locale = models.CharField(max_length=10, default='en')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.email
