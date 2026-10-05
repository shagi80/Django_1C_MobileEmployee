from django.urls import path

from .views import (
    HealthCheckView,
    ServerTimeView,
    ChangedGoodsDateRangeView,
    GoodBulkCreateView,
    StorageListView,
    GoodImageUploadView,
    StorageBalanceListView
)


urlpatterns = [
    path('server/health/', HealthCheckView.as_view(), name='health_check'),
    path('server/time/', ServerTimeView.as_view(), name='get_time'),
   
    path('goods/changed_goods/', ChangedGoodsDateRangeView.as_view(), name='get_changed_goods'),
    path('goods/add_goods/', GoodBulkCreateView.as_view(), name='add_goods'),
    path('goods/<uuid:sync_code>/upload_image/', GoodImageUploadView.as_view(), name='good-upload-image'),

    path('storages/get_list/', StorageListView.as_view(), name='get_storages'),
    path('storages/get_balance/', StorageBalanceListView.as_view(), name='get_balance'),
   
]