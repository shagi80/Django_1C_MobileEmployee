from django.urls import path

from .views import (
    HealthCheckView,
    ServerTimeView,
    UnifiedSyncView,
    SyncMobileUsersView,
    UnifiedDocumentView
)


urlpatterns = [
    path('server/health/', HealthCheckView.as_view(), name='health_check'),
    path('server/time/', ServerTimeView.as_view(), name='get_time'),
    path('sync/data/', UnifiedSyncView.as_view(), name='unified_sync'),
    path('sync/document/', UnifiedDocumentView.as_view(), name='document_sync'),
    path('mobileusers/', SyncMobileUsersView.as_view(), name='mobile_users_sync'),
]
