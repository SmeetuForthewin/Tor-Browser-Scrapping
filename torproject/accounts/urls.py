from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # FIX: URL names now match what's used in templates (base.html, login.html)
    # and what views redirect to
    path('login/', views.login_view, name='login_view'),
    path('logout/', views.logout_view, name='logout_view'),
    path('dashboard/', views.dashboard_view, name='dashboard_view'),
    path('create-user/', views.create_user_view, name='create_user_view'),
]