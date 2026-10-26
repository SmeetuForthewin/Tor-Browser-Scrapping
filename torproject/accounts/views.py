from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages


def login_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard_view')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('accounts:dashboard_view')
        else:
            messages.error(request, 'Invalid credentials. Access denied.')

    # FIX: Correct template path (was missing, now points to accounts/login.html)
    return render(request, 'accounts/login.html')


def logout_view(request):
    logout(request)
    return redirect('accounts:login_view')


@login_required
def dashboard_view(request):
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    admins = User.objects.filter(is_superuser=True).count()
    recent_users = User.objects.order_by('-date_joined')[:5]
    context = {
        'total_users': total_users,
        'active_users': active_users,
        'admins': admins,
        'recent_users': recent_users,
    }
    # FIX: Correct template path
    return render(request, 'dashboard/dashboard.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def create_user_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        email = request.POST.get('email', '').strip()
        is_staff = request.POST.get('is_staff') == 'on'

        if not username or not password:
            messages.error(request, 'Username and password are required.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, f'Username "{username}" already exists.')
        elif len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        else:
            User.objects.create_user(
                username=username,
                password=password,
                email=email,
                is_staff=is_staff,
            )
            messages.success(request, f'User "{username}" created successfully.')
            return redirect('accounts:create_user_view')

    all_users = User.objects.all().order_by('-date_joined')
    return render(request, 'dashboard/create_user.html', {'all_users': all_users})