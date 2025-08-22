from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.templatetags.static import static
from user_agents import parse
import json
import requests
from datetime import datetime, timedelta
from .models import URL, ClickAnalytics, UserProfile, Notification, URLCategory
from shortener.utils import get_location_from_ip, extract_url_info, generate_pdf_report

def index(request):
    """الصفحة الرئيسية مع الإحصائيات"""
    # إحصائيات عامة
    total_urls = URL.objects.count()
    total_clicks = sum(URL.objects.values_list('click_count', flat=True))
    total_users = User.objects.count()
    
    # الروابط الأخيرة (عامة فقط)
    recent_urls = URL.objects.filter(is_private=False, user__isnull=True)[:5]
    
    # الروابط الأكثر نقراً
    popular_urls = URL.objects.filter(is_private=False).order_by('-click_count')[:5]
    
    context = {
        'total_urls': total_urls,
        'total_clicks': total_clicks,
        'total_users': total_users,
        'recent_urls': recent_urls,
        'popular_urls': popular_urls,
        'categories': URLCategory.objects.all()
    }
    return render(request, 'shortener/index.html', context)

@login_required
def dashboard(request):
    """لوحة تحكم المستخدم"""
    user_urls = URL.objects.filter(user=request.user)
    
    # إحصائيات المستخدم
    stats = {
        'total_urls': user_urls.count(),
        'total_clicks': sum(user_urls.values_list('click_count', flat=True)),
        'active_urls': user_urls.filter(is_active=True).count(),
        'expired_urls': user_urls.filter(expires_at__lt=timezone.now()).count(),
    }
    
    # الروابط الأخيرة
    recent_urls = user_urls[:10]
    
    # بيانات الرسم البياني (آخر 30 يوم)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    daily_clicks = []
    
    for i in range(30):
        date = thirty_days_ago + timedelta(days=i)
        clicks = ClickAnalytics.objects.filter(
            url__user=request.user,
            clicked_at__date=date.date()
        ).count()
        daily_clicks.append({
            'date': date.strftime('%Y-%m-%d'),
            'clicks': clicks
        })
    
    # الإشعارات
    notifications = Notification.objects.filter(user=request.user, is_read=False)[:5]
    
    context = {
        'stats': stats,
        'recent_urls': recent_urls,
        'daily_clicks': json.dumps(daily_clicks),
        'notifications': notifications,
    }
    return render(request, 'shortener/dashboard.html', context)

def advanced_shorten(request):
    """صفحة الاختصار المتقدم"""
    if request.method == 'POST':
        original_url = request.POST.get('url')
        custom_alias = request.POST.get('custom_alias', '').strip()
        password = request.POST.get('password', '').strip()
        expires_days = request.POST.get('expires_days')
        category_id = request.POST.get('category')
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        tags = request.POST.get('tags', '').strip()
        is_private = request.POST.get('is_private') == 'on'
        
        if not original_url:
            messages.error(request, 'يرجى إدخال رابط صحيح')
            return redirect('advanced_shorten')
        
        # إضافة http إذا لم يكن موجود
        if not original_url.startswith(('http://', 'https://')):
            original_url = 'http://' + original_url
        
        # التحقق من الرمز المخصص
        if custom_alias:
            if URL.objects.filter(custom_alias=custom_alias).exists():
                messages.error(request, 'الرمز المخصص مستخدم بالفعل')
                return redirect('advanced_shorten')
        
        # استخراج معلومات الصفحة
        if not title:
            url_info = extract_url_info(original_url)
            title = url_info.get('title', '')
            if not description:
                description = url_info.get('description', '')
        
        # إنشاء الرابط
        url_obj = URL.objects.create(
            original_url=original_url,
            custom_alias=custom_alias if custom_alias else None,
            user=request.user if request.user.is_authenticated else None,
            password=password,
            title=title,
            description=description,
            tags=tags,
            is_private=is_private,
            category_id=category_id if category_id else None
        )
        
        # تاريخ الانتهاء
        if expires_days:
            url_obj.expires_at = timezone.now() + timedelta(days=int(expires_days))
            url_obj.save()
        
        # إشعار للمستخدم المسجل
        if request.user.is_authenticated:
            Notification.objects.create(
                user=request.user,
                title='تم إنشاء رابط جديد',
                message=f'تم إنشاء الرابط المختصر: {url_obj.get_short_url()}',
                type='success'
            )
        
        messages.success(request, f'تم إنشاء الرابط المختصر: {url_obj.get_short_url()}')
        
        if request.user.is_authenticated:
            return redirect('dashboard')
        
    categories = URLCategory.objects.all()
    return render(request, 'shortener/advanced_shorten.html', {'categories': categories})

def redirect_url(request, short_code):
    """إعادة توجيه مع تحليلات متقدمة"""
    # البحث بالكود أو الرمز المخصص
    url_obj = get_object_or_404(
        URL, 
        Q(short_code=short_code) | Q(custom_alias=short_code)
    )
    
    # التحقق من الانتهاء
    if url_obj.is_expired():
        return render(request, 'shortener/expired.html', {'url': url_obj})
    
    # التحقق من كلمة المرور
    if url_obj.password:
        if request.method == 'POST':
            entered_password = request.POST.get('password')
            if entered_password != url_obj.password:
                messages.error(request, 'كلمة مرور خاطئة')
                return render(request, 'shortener/password_required.html', {'url': url_obj})
        else:
            return render(request, 'shortener/password_required.html', {'url': url_obj})
    
    # جمع بيانات التحليل
    user_agent = parse(request.META.get('HTTP_USER_AGENT', ''))
    ip_address = get_client_ip(request)
    
    # التحقق من النقرة الفريدة
    is_unique = not ClickAnalytics.objects.filter(
        url=url_obj, 
        ip_address=ip_address
    ).exists()
    
    # حفظ التحليلات
    location_data = get_location_from_ip(ip_address)
    analytics = ClickAnalytics.objects.create(
        url=url_obj,
        ip_address=ip_address,
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        referer=request.META.get('HTTP_REFERER', ''),
        country=location_data.get('country', ''),
        city=location_data.get('city', ''),
        device_type=get_device_type(user_agent),
        browser=user_agent.browser.family,
        os=user_agent.os.family,
        is_unique=is_unique
    )
    
    # تحديث العدادات
    url_obj.click_count += 1
    if is_unique:
        url_obj.unique_clicks += 1
    url_obj.last_clicked = timezone.now()
    url_obj.save()
    
    return redirect(url_obj.original_url)

@login_required
def url_analytics(request, short_code):
    """صفحة التحليلات المتقدمة"""
    url_obj = get_object_or_404(
        URL, 
        Q(short_code=short_code) | Q(custom_alias=short_code),
        user=request.user
    )
    
    analytics = url_obj.analytics.all()
    
    # تجميع البيانات
    countries = analytics.values('country').annotate(count=Count('id')).order_by('-count')
    devices = analytics.values('device_type').annotate(count=Count('id')).order_by('-count')
    browsers = analytics.values('browser').annotate(count=Count('id')).order_by('-count')
    
    # البيانات اليومية (آخر 30 يوم)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    daily_data = []
    
    for i in range(30):
        date = thirty_days_ago + timedelta(days=i)
        clicks = analytics.filter(clicked_at__date=date.date()).count()
        daily_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'clicks': clicks
        })
    
    context = {
        'url': url_obj,
        'analytics': analytics[:50],  # آخر 50 نقرة
        'countries': countries,
        'devices': devices,
        'browsers': browsers,
        'daily_data': json.dumps(daily_data),
    }
    
    return render(request, 'shortener/analytics.html', context)

# API Views
@csrf_exempt
def api_shorten(request):
    """API متقدم لاختصار الروابط"""
    if request.method == 'POST':
        try:
            # التحقق من API key
            api_key = request.headers.get('X-API-Key')
            user = None
            
            if api_key:
                try:
                    profile = UserProfile.objects.get(api_key=api_key)
                    user = profile.user
                    
                    # التحقق من حد الاستخدام
                    if profile.api_calls_count >= profile.api_calls_limit:
                        return JsonResponse({
                            'error': 'API limit exceeded'
                        }, status=429)
                    
                    profile.api_calls_count += 1
                    profile.save()
                    
                except UserProfile.DoesNotExist:
                    return JsonResponse({
                        'error': 'Invalid API key'
                    }, status=401)
            
            data = json.loads(request.body)
            original_url = data.get('url')
            
            if not original_url:
                return JsonResponse({'error': 'URL is required'}, status=400)
            
            # إنشاء الرابط
            url_obj = URL.objects.create(
                original_url=original_url,
                user=user,
                custom_alias=data.get('custom_alias'),
                title=data.get('title', ''),
                description=data.get('description', ''),
                password=data.get('password', ''),
                is_private=data.get('is_private', False)
            )
            
            # تاريخ الانتهاء
            if data.get('expires_days'):
                url_obj.expires_at = timezone.now() + timedelta(days=int(data.get('expires_days')))
                url_obj.save()
            
            return JsonResponse({
                'short_url': url_obj.get_short_url(),
                'short_code': url_obj.short_code,
                'original_url': url_obj.original_url,
                'qr_code': url_obj.qr_code,
                'created_at': url_obj.created_at.isoformat(),
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

# Utility Functions
def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def get_device_type(user_agent):
    if user_agent.is_mobile:
        return 'mobile'
    elif user_agent.is_tablet:
        return 'tablet'
    elif user_agent.is_pc:
        return 'desktop'
    else:
        return 'unknown'
    
def shorten_url(request):
    """Create a shortened URL"""
    if request.method == 'POST':
        original_url = request.POST.get('url')
        
        if not original_url:
            messages.error(request, 'يرجى إدخال رابط صحيح')
            return redirect('index')
        
        # Add http:// if not present
        if not original_url.startswith(('http://', 'https://')):
            original_url = 'http://' + original_url
        
        # Check if URL already exists
        existing_url = URL.objects.filter(original_url=original_url).first()
        if existing_url:
            messages.success(request, f'الرابط المختصر: {existing_url.get_short_url()}')
            return redirect('index')
        
        # Create new shortened URL
        url_obj = URL.objects.create(original_url=original_url)
        messages.success(request, f'تم إنشاء الرابط المختصر: {url_obj.get_short_url()}')
        
    return redirect('index')

def redirect_url(request, short_code):
    """Redirect to original URL and increment click count"""
    url_obj = get_object_or_404(URL, short_code=short_code)
    url_obj.click_count += 1
    url_obj.save()
    return redirect(url_obj.original_url)

def url_stats(request, short_code):
    """Show statistics for a shortened URL"""
    url_obj = get_object_or_404(URL, short_code=short_code)
    context = {
        'url': url_obj
    }
    return render(request, 'shortener/stats.html', context)

def advanced_shorten(request):
    """صفحة الاختصار المتقدم"""
    if request.method == 'POST':
        original_url = request.POST.get('url')
        custom_alias = request.POST.get('custom_alias', '').strip()
        password = request.POST.get('password', '').strip()
        expires_days = request.POST.get('expires_days')
        category_id = request.POST.get('category')
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        tags = request.POST.get('tags', '').strip()
        is_private = request.POST.get('is_private') == 'on'
        
        if not original_url:
            messages.error(request, 'يرجى إدخال رابط صحيح')
            return redirect('advanced_shorten')
        
        # إضافة http إذا لم يكن موجود
        if not original_url.startswith(('http://', 'https://')):
            original_url = 'http://' + original_url
        
        # التحقق من الرمز المخصص
        if custom_alias:
            if URL.objects.filter(custom_alias=custom_alias).exists():
                messages.error(request, 'الرمز المخصص مستخدم بالفعل')
                return redirect('advanced_shorten')
        
        # استخراج معلومات الصفحة
        if not title:
            url_info = extract_url_info(original_url)
            title = url_info.get('title', '')
            if not description:
                description = url_info.get('description', '')
        
        # إنشاء الرابط
        url_obj = URL.objects.create(
            original_url=original_url,
            custom_alias=custom_alias if custom_alias else None,
            user=request.user if request.user.is_authenticated else None,
            password=password,
            title=title,
            description=description,
            tags=tags,
            is_private=is_private,
            category_id=category_id if category_id else None
        )
        
        # تاريخ الانتهاء
        if expires_days:
            url_obj.expires_at = timezone.now() + timedelta(days=int(expires_days))
            url_obj.save()
        
        # إشعار للمستخدم المسجل
        if request.user.is_authenticated:
            Notification.objects.create(
                user=request.user,
                title='تم إنشاء رابط جديد',
                message=f'تم إنشاء الرابط المختصر: {url_obj.get_short_url()}',
                type='success'
            )
        
        messages.success(request, f'تم إنشاء الرابط المختصر: {url_obj.get_short_url()}')
        
        if request.user.is_authenticated:
            return redirect('dashboard')
        
    categories = URLCategory.objects.all()
    return render(request, 'shortener/advanced_shorten.html', {'categories': categories})



def logout(request):
    """تسجيل خروج المستخدم"""
    from django.contrib.auth import logout as auth_logout
    auth_logout(request)
    messages.info(request, 'تم تسجيل الخروج بنجاح')
    return redirect('index')

def mark_notification_read(request, notification_id):
    """وضع علامة على الإشعار كمقروء"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.save()
    return redirect('dashboard')
# urlshortener/settings.py

def get_device_type(user_agent):
    if user_agent.is_mobile:
        return 'mobile'
    elif user_agent.is_tablet:
        return 'tablet'
    elif user_agent.is_pc:
        return 'desktop'
    else:
        return 'unknown'

def shorten_url(request):
     if request.method == 'POST':
        original_url = request.POST.get('url')
        
        if not original_url:
            messages.error(request, 'يرجى إدخال رابط صحيح')
            return redirect('index')
        
        # Add http:// if not present
        if not original_url.startswith(('http://', 'https://')):
            original_url = 'http://' + original_url
        
        # Check if URL already exists
        existing_url = URL.objects.filter(original_url=original_url).first()
        if existing_url:
            messages.success(request, f'الرابط المختصر: {existing_url.get_short_url()}')
            return redirect('index')
        
        # Create new shortened URL
        url_obj = URL.objects.create(original_url=original_url)
        messages.success(request, f'تم إنشاء الرابط المختصر: {url_obj.get_short_url()}')

        return redirect('index')
     
def redirect_url(request, short_code):
    """Redirect to original URL and increment click count"""
    url_obj = get_object_or_404(URL, short_code=short_code)
    url_obj.click_count += 1
    url_obj.save()
    return redirect(url_obj.original_url)

def url_stats(request, short_code):
    """Show statistics for a shortened URL"""
    url_obj = get_object_or_404(URL, short_code=short_code)
    context = {
        'url': url_obj
    }
    return render(request, 'shortener/stats.html', context)

def Comming_Soon_Page(request):
    return render (request, 'shortener/Comming_Soon_Page.html')