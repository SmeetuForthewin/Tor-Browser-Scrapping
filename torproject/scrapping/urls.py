from django.urls import path
from scrapping.views import *

app_name = 'scrapping'

urlpatterns = [
      path('scrape/',        scrape_ahmia_view,   name='scrape_ahmia_view'),
      path('scrape/run/',    scrape_ahmia_run,    name='scrape_ahmia_run'),
      path('scrape/stream/', scrape_ahmia_stream, name='scrape_ahmia_stream'),
      path('scrape/save/', scrape_ahmia_save, name='scrape_ahmia_save')
]