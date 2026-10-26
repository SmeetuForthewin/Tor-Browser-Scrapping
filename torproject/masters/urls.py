from django.urls import path
from . import views

app_name = 'masters'

urlpatterns = [
    # Keywords master
    path('keywords/', views.keywords_view, name='keywords_view'),
    path('keywords/<int:pk>/edit/', views.keyword_edit_view, name='keyword_edit_view'),
    path('keywords/<int:pk>/delete/', views.keyword_delete_view, name='keyword_delete_view'),

    # User management with keywords
    path('users/create/', views.create_user_view, name='create_user_view'),
    path('users/', views.users_list_view, name='users_list_view'),
    path('users/<int:user_id>/keywords/', views.user_keywords_update_view, name='user_keywords_update_view'),
]