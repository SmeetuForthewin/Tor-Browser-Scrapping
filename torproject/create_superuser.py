#!/usr/bin/env python
"""
Run this once after migrations to create the default superuser.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'torproject.settings')
django.setup()

from django.contrib.auth.models import User

USERNAME = 'admin'
PASSWORD = 'Admin@1234'
EMAIL = 'admin@tor.local'

if not User.objects.filter(username=USERNAME).exists():
    User.objects.create_superuser(username=USERNAME, password=PASSWORD, email=EMAIL)
    print(f'[+] Superuser created: {USERNAME} / {PASSWORD}')
else:
    print(f'[!] Superuser "{USERNAME}" already exists.')