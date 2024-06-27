"""
URL configuration for tonano project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from indexer.views import WalletByAddressView, WalletByAddressAndTickView, TickByTickView, Ton20TickListView, \
    TransactionByTickView, TransactionListView, TransactionByHashView, LatestStateBOCView

schema_view = get_schema_view(
    openapi.Info(
        title="ton20 api",
        default_version='v1',
        description="API ton20",
        terms_of_service="https://www.google.com/policies/terms/",
        contact=openapi.Contact(email="hello@head-labs.com"),
        license=openapi.License(name="BSD License"),
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('swagger.yaml', schema_view.without_ui(cache_timeout=0), name='schema-yaml'),
    path('api/v1/wallet/<str:address>/', WalletByAddressView.as_view(), name='wallet-by-address'),
    path('api/v1/latest-state-boc/', LatestStateBOCView.as_view(), name='latest-state-boc'),
    path('api/v1/wallet/<str:address>/<str:tick>/', WalletByAddressAndTickView.as_view(),
         name='wallet-by-address-and-tick'),
    path('api/v1/ticks/', Ton20TickListView.as_view(), name='tick-list'),
    path('api/v1/ticks/<str:tick>/', TickByTickView.as_view(), name='tick-by-tick'),
    path('api/v1/transactions/tick/<str:tick>/', TransactionByTickView.as_view(), name='transaction-by-tick'),
    path('api/v1/transactions/<str:initiator>/', TransactionListView.as_view(), name='transaction-list'),
    path('api/v1/transaction/<str:transaction_hash>/', TransactionByHashView.as_view(), name='transaction-by-hash'),
    path('', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
]