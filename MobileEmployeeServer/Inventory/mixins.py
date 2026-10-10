import base64
from django.contrib.auth import authenticate
from django.http import JsonResponse
from rest_framework.response import Response


class BasicAuthMixin:
    """Базовая аутентификация для 1С (исправленная версия, не ломающая рендереры)"""
    
    def dispatch(self, request, *args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Basic '):
            # Переводим на JsonResponse — это защищает жизненный цикл Django и DRF
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        
        try:
            auth_decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
            username, password = auth_decoded.split(':', 1)
        except Exception:
            return JsonResponse({'error': 'Invalid auth format'}, status=401)
        
        user = authenticate(request, username=username, password=password)
        
        if not user:
            return JsonResponse({'error': 'Invalid credentials'}, status=401)
        
        request.user = user
        return super().dispatch(request, *args, **kwargs)
  
    
class PaginationMixin:
    """Миксин для пагинации"""
    
    def get_pagination_params(self, request, max_page_size=200, default_page_size=100):
        """Получить параметры пагинации"""
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', default_page_size))
        
        if page_size > max_page_size:
            page_size = max_page_size
        
        return page, page_size
    
    def paginate_queryset(self, queryset, page, page_size):
        """Применить пагинацию к queryset"""
        from django.core.paginator import Paginator
        paginator = Paginator(queryset, page_size)
        
        if page > paginator.num_pages and queryset.count() > 0:
            return None, Response({
                'error': 'Page not found',
                'message': f'Page {page} does not exist. Total pages: {paginator.num_pages}'
            }, status=404)
        
        current_page = paginator.get_page(page)
        
        pagination_info = {
            'current_page': page,
            'page_size': page_size,
            'total_pages': paginator.num_pages,
            'total_records': paginator.count,
            'has_next': current_page.has_next(),
            'has_previous': current_page.has_previous(),
            'next_page': page + 1 if current_page.has_next() else None,
            'previous_page': page - 1 if current_page.has_previous() else None
        }
        
        return current_page, pagination_info
    









