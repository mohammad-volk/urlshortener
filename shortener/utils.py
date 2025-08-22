import requests
from bs4 import BeautifulSoup
from django.core.mail import send_mail
from django.conf import settings
import geoip2.database
import geoip2.errors
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import csv
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Count
from datetime import timedelta

def extract_url_info(url):
    """استخراج معلومات الصفحة من الرابط"""
    try:
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; UrlPro/1.0)'
        })
        soup = BeautifulSoup(response.content, 'html.parser')
        
        title = soup.find('title')
        title = title.get_text().strip() if title else ''
        
        description = soup.find('meta', attrs={'name': 'description'})
        description = description.get('content', '').strip() if description else ''
        
        return {
            'title': title[:200],
            'description': description[:300],
            'status_code': response.status_code
        }
    except:
        return {'title': '', 'description': '', 'status_code': 0}

def get_location_from_ip(ip_address):
    """الحصول على الموقع الجغرافي من IP"""
    try:
        # يمكنك تحميل قاعدة بيانات GeoLite2 مجاناً من MaxMind
        with geoip2.database.Reader('path/to/GeoLite2-City.mmdb') as reader:
            response = reader.city(ip_address)
            return {
                'country': response.country.names.get('ar', response.country.name),
                'city': response.city.names.get('ar', response.city.name),
            }
    except:
        return {'country': 'غير معروف', 'city': 'غير معروف'}

def generate_csv_export(user):
    """تصدير بيانات المستخدم إلى CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="urls_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['الرابط الأصلي', 'الرابط المختصر', 'العنوان', 'النقرات', 'تاريخ الإنشاء'])
    
    for url in user.url_set.all():
        writer.writerow([
            url.original_url,
            url.get_short_url(),
            url.title,
            url.click_count,
            url.created_at.strftime('%Y-%m-%d %H:%M')
        ])
    
    return response

def generate_pdf_report(user):
    """إنشاء تقرير PDF للمستخدم"""
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="monthly_report.pdf"'
    
    p = canvas.Canvas(response, pagesize=letter)
    
    # عنوان التقرير
    p.drawString(100, 750, f"تقرير شهري للمستخدم: {user.username}")
    
    # الإحصائيات
    y_position = 700
    urls = user.url_set.all()
    total_urls = urls.count()
    total_clicks = sum(urls.values_list('click_count', flat=True))
    
    p.drawString(100, y_position, f"إجمالي الروابط: {total_urls}")
    p.drawString(100, y_position-20, f"إجمالي النقرات: {total_clicks}")
    
    # قائمة الروابط
    y_position -= 60
    p.drawString(100, y_position, "قائمة الروابط:")
    y_position -= 20
    
    for url in urls[:20]:  # أول 20 رابط
        p.drawString(120, y_position, f"• {url.title or url.original_url[:50]}...")
        p.drawString(400, y_position, f"{url.click_count} نقرة")
        y_position -= 15
        
        if y_position < 100:
            break
    
    p.showPage()
    p.save()
    return response

def send_weekly_report(user):
    """إرسال تقرير أسبوعي بالبريد الإلكتروني"""
    if not user.userprofile.weekly_reports:
        return
    
    urls = user.url_set.all()
    total_clicks_week = sum(
        url.analytics.filter(
            clicked_at__gte=timezone.now() - timedelta(days=7)
        ).count() for url in urls
    )
    
    subject = f'تقريرك الأسبوعي - UrlPro'
    message = f'''
    مرحباً {user.username}،
    
    إليك تقريرك الأسبوعي:
    
    📊 إجمالي النقرات هذا الأسبوع: {total_clicks_week}
    🔗 إجمالي الروابط النشطة: {urls.filter(is_active=True).count()}
    
    يمكنك مراجعة التفاصيل الكاملة في لوحة التحكم.
    
    تحياتنا،
    فريق UrlPro
    '''
    
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    )

class RateLimiter:
    """نظام تحديد المعدل للAPI"""
    
    @staticmethod
    def check_rate_limit(user_profile, limit_type='api'):
        if limit_type == 'api':
            if user_profile.api_calls_count >= user_profile.api_calls_limit:
                return False
            user_profile.api_calls_count += 1
            user_profile.save()
        return True

def clean_expired_urls():
    """تنظيف الروابط المنتهية الصلاحية"""
    from .models import URL
    expired_urls = URL.objects.filter(
        expires_at__lt=timezone.now(),
        is_active=True
    )
    
    count = expired_urls.count()
    expired_urls.update(is_active=False)
    
    return count

def generate_analytics_data(url_obj, days=30):
    """إنشاء بيانات التحليلات لرابط معين"""
    from datetime import datetime, timedelta
    from .models import ClickAnalytics
    
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    analytics = url_obj.analytics.filter(
        clicked_at__gte=start_date,
        clicked_at__lte=end_date
    )
    
    # تجميع البيانات حسب اليوم
    daily_clicks = {}
    for i in range(days):
        date = start_date + timedelta(days=i)
        daily_clicks[date.strftime('%Y-%m-%d')] = 0
    
    for click in analytics:
        date_str = click.clicked_at.strftime('%Y-%m-%d')
        if date_str in daily_clicks:
            daily_clicks[date_str] += 1
    
    return {
        'daily_clicks': daily_clicks,
        'total_clicks': analytics.count(),
        'unique_clicks': analytics.filter(is_unique=True).count(),
        'countries': list(analytics.values('country').annotate(
            count=Count('id')
        ).order_by('-count')[:10]),
        'devices': list(analytics.values('device_type').annotate(
            count=Count('id')
        ).order_by('-count')),
        'browsers': list(analytics.values('browser').annotate(
            count=Count('id')
        ).order_by('-count')[:10]),
    }