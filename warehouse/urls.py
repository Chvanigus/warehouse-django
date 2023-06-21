"""URL configuration for warehouse project."""
from django.contrib import admin
from django.urls import path, include
from spares import urls as spares_urls

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include(spares_urls)),
    path("__debug__/", include("debug_toolbar.urls")),
    path("select2/", include("django_select2.urls")),
]
