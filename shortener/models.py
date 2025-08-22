from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import URLValidator
import string
import random
import qrcode
import io
import base64
from PIL import Image

def generate_short_code():
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(6))

class Domain(models.Model):
    name = models.CharField(max_length=100, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return self.name

class URLCategory(models.Model):
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default='#007bff')  # Hex color
    icon = models.CharField(max_length=50, default='🔗')
    
    def __str__(self):
        return self.name

class URL(models.Model):
    original_url = models.URLField(max_length=2000)
    short_code = models.CharField(max_length=15, unique=True, default=generate_short_code)
    custom_alias = models.CharField(max_length=50, blank=True, null=True, unique=True)
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    
    # User and Organization
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    category = models.ForeignKey(URLCategory, on_delete=models.SET_NULL, null=True, blank=True)
    domain = models.ForeignKey(Domain, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Security
    password = models.CharField(max_length=100, blank=True)
    is_private = models.BooleanField(default=False)
    
    # Timing
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Analytics
    click_count = models.IntegerField(default=0)
    unique_clicks = models.IntegerField(default=0)
    last_clicked = models.DateTimeField(null=True, blank=True)
    
    # Features
    qr_code = models.TextField(blank=True)  # Base64 encoded QR code
    is_active = models.BooleanField(default=True)
    tags = models.CharField(max_length=500, blank=True)  # Comma separated
    
    # SEO
    meta_title = models.CharField(max_length=150, blank=True)
    meta_description = models.CharField(max_length=300, blank=True)
    
    def save(self, *args, **kwargs):
        if not self.qr_code:
            self.generate_qr_code()
        super().save(*args, **kwargs)
    
    def generate_qr_code(self):
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(self.get_short_url())
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        self.qr_code = base64.b64encode(buffer.getvalue()).decode()
    
    def get_short_url(self):
        code = self.custom_alias or self.short_code
        domain = self.domain.name if self.domain else "127.0.0.1:8000"
        return f"http://{domain}/{code}"
    
    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False
    
    def get_tags_list(self):
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
    
    def __str__(self):
        return f"{self.original_url} -> {self.short_code}"
    
    class Meta:
        ordering = ['-created_at']

class ClickAnalytics(models.Model):
    url = models.ForeignKey(URL, on_delete=models.CASCADE, related_name='analytics')
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    referer = models.URLField(blank=True, null=True)
    
    # Geographic data
    country = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    
    # Device info
    device_type = models.CharField(max_length=50, blank=True)  # mobile, desktop, tablet
    browser = models.CharField(max_length=100, blank=True)
    os = models.CharField(max_length=100, blank=True)
    
    clicked_at = models.DateTimeField(default=timezone.now)
    is_unique = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-clicked_at']

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)
    website = models.URLField(blank=True)
    
    # Subscription
    is_premium = models.BooleanField(default=False)
    premium_expires = models.DateTimeField(null=True, blank=True)
    
    # Preferences
    email_notifications = models.BooleanField(default=True)
    weekly_reports = models.BooleanField(default=True)
    
    # API
    api_key = models.CharField(max_length=100, unique=True, blank=True)
    api_calls_count = models.IntegerField(default=0)
    api_calls_limit = models.IntegerField(default=1000)  # Per month
    
    created_at = models.DateTimeField(default=timezone.now)
    
    def generate_api_key(self):
        if not self.api_key:
            chars = string.ascii_letters + string.digits
            self.api_key = ''.join(random.choice(chars) for _ in range(32))
            self.save()
        return self.api_key

class Notification(models.Model):
    TYPES = [
        ('info', 'معلومات'),
        ('success', 'نجاح'),
        ('warning', 'تحذير'),
        ('error', 'خطأ'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    message = models.TextField()
    type = models.CharField(max_length=20, choices=TYPES, default='info')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-created_at']