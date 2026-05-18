from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.admin_login, name='admin_login'),
    path('logout/', views.admin_logout, name='admin_logout'),
    path('', views.dashboard, name='admin_dashboard'),
    path('orders/', views.orders_list, name='admin_orders'),
    path('orders/<int:pk>/', views.order_detail, name='admin_order_detail'),
    path('products/', views.products_list, name='admin_products'),
    path('products/add/', views.product_edit, name='admin_product_add'),
    path('products/<int:pk>/edit/', views.product_edit, name='admin_product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='admin_product_delete'),
    path('categories/', views.categories_list, name='admin_categories'),
    path('categories/add/', views.category_edit, name='admin_category_add'),
    path('categories/<int:pk>/edit/', views.category_edit, name='admin_category_edit'),
    path('customers/', views.customers_list, name='admin_customers'),
    path('customers/<int:pk>/edit/', views.customer_edit, name='admin_customer_edit'),
    path('customers/<int:pk>/delete/', views.customer_delete, name='admin_customer_delete'),
    path('excel/template/', views.excel_download_template, name='admin_excel_template'),
    path('excel/import/', views.excel_import, name='admin_excel_import'),
    path('ai/', views.ai_dashboard, name='admin_ai'),
    path('ai/categorize/', views.ai_categorize, name='admin_ai_categorize'),
    path('ai/images/', views.ai_fetch_images, name='admin_ai_images'),
    path('ai/site-search/', views.ai_site_search, name='admin_ai_site_search'),
]
