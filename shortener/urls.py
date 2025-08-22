from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
     path('dashboard/', views.dashboard, name='dashboard'),
     path('advanced_shorten', views.advanced_shorten, name='api_shorten'),
    path('shorten_url', views.shorten_url, name='shorten_url'),
        path('url_analytics/<str:short_code>', views.url_analytics, name='url_analytics'),

     path('advanced_shorten', views.advanced_shorten, name='advanced_shorten'),
     path('api/shorten/', views.api_shorten, name='api_shorten'),
    path('stats/<str:short_code>/', views.url_stats, name='url_stats'),
    path('<str:short_code>/', views.redirect_url, name='redirect_url'),
    path('login/', views.login, name='login'),
     path('logout/', views.logout, name='logout'),
]