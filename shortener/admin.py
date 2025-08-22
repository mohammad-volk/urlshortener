from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import URL, UserProfile
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'bio')
    search_fields = ('user__username', 'bio')

@admin.register(URL)
class URLAdmin(admin.ModelAdmin):
    list_display = ('short_code', 'original_url', 'click_count', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('original_url', 'short_code')
    readonly_fields = ('created_at', 'click_count')