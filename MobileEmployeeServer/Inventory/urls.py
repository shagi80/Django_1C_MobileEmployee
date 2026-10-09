from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    HealthCheckView,
    ServerTimeView,
    UnifiedSyncView,
    SyncModelTypesView,
    MobileUserViewSet
)

# Создаем роутер и регистрируем в нем мобильных пользователей
router = DefaultRouter()
router.register(r'users', MobileUserViewSet, basename='mobile_users')

urlpatterns = [
    path('server/health/', HealthCheckView.as_view(), name='health_check'),
    path('server/time/', ServerTimeView.as_view(), name='get_time'),
    path('sync/data/', UnifiedSyncView.as_view(), name='unified_sync'),
    path('sync/types/', SyncModelTypesView.as_view(), name='sync_model_types'),
    path('mobile/', include(router.urls)),
   
]