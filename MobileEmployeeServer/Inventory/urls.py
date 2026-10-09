from django.urls import path

from .views import (
    HealthCheckView,
    ServerTimeView,
    UnifiedSyncView,
    SyncModelTypesView
)


urlpatterns = [
    path('server/health/', HealthCheckView.as_view(), name='health_check'),
    path('server/time/', ServerTimeView.as_view(), name='get_time'),
    path('sync/data/', UnifiedSyncView.as_view(), name='unified_sync'),
    path('sync/types/', SyncModelTypesView.as_view(), name='sync_model_types')
   
]