from django.urls import path
from . import views

app_name = 'report'

urlpatterns = [
    path('',        views.report_view,     name='report_view'),
    path('pdf/',    views.report_pdf_view, name='report_pdf_view'),
    path('black_market/',    views.black_market, name='black_market'),

]