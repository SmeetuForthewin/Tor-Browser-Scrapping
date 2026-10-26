from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json

from .models import Keyword, UserKeyword

superuser_required = user_passes_test(lambda u: u.is_superuser)


# ─── KEYWORDS MASTER ───────────────────────────────────────────────────────────

@login_required
@superuser_required
def keywords_view(request):
    """List all keywords + create new keyword."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        color = request.POST.get('color', '#0ea5e9').strip()

        if not name:
            messages.error(request, 'Keyword name is required.')
        elif Keyword.objects.filter(name__iexact=name).exists():
            messages.error(request, f'Keyword "{name}" already exists.')
        else:
            Keyword.objects.create(
                name=name,
                description=description,
                color=color,
                created_by=request.user,
            )
            messages.success(request, f'Keyword "{name}" created successfully.')
            return redirect('masters:keywords_view')
    color_presets = [
        '#0ea5e9',
        '#8b5cf6',
        '#f43f5e',
        '#f59e0b',
        '#10b981',
        '#6366f1',
        '#ec4899',
        '#14b8a6',
    ]

    keywords = Keyword.objects.select_related('created_by').all()
    return render(request, 'masters/keywords.html', {'keywords': keywords,        'color_presets': color_presets,
})


@login_required
@superuser_required
def keyword_edit_view(request, pk):
    """Edit a keyword (AJAX + regular POST)."""
    keyword = get_object_or_404(Keyword, pk=pk)

    if request.method == 'POST':
        # Support both JSON (fetch) and form POST
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body)
        else:
            data = request.POST

        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        color = data.get('color', keyword.color).strip()

        if not name:
            if request.content_type and 'application/json' in request.content_type:
                return JsonResponse({'ok': False, 'error': 'Name is required.'})
            messages.error(request, 'Keyword name is required.')
        elif Keyword.objects.filter(name__iexact=name).exclude(pk=pk).exists():
            if request.content_type and 'application/json' in request.content_type:
                return JsonResponse({'ok': False, 'error': f'"{name}" already exists.'})
            messages.error(request, f'Keyword "{name}" already exists.')
        else:
            keyword.name = name
            keyword.description = description
            keyword.color = color
            keyword.save()
            if request.content_type and 'application/json' in request.content_type:
                return JsonResponse({'ok': True, 'name': keyword.name, 'color': keyword.color, 'description': keyword.description})
            messages.success(request, f'Keyword "{name}" updated.')
            return redirect('masters:keywords_view')

    return redirect('masters:keywords_view')


@login_required
@superuser_required
@require_POST
def keyword_delete_view(request, pk):
    """Delete a keyword."""
    keyword = get_object_or_404(Keyword, pk=pk)
    name = keyword.name
    keyword.delete()
    messages.success(request, f'Keyword "{name}" deleted.')
    return redirect('masters:keywords_view')


# ─── USER CREATION WITH KEYWORD ASSIGNMENT ────────────────────────────────────

@login_required
@superuser_required
def create_user_view(request):
    """Create user and optionally assign keywords."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        email = request.POST.get('email', '').strip()
        is_staff = request.POST.get('is_staff') == 'on'
        keyword_ids = request.POST.getlist('keywords')  # list of keyword PKs

        if not username or not password:
            messages.error(request, 'Username and password are required.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, f'Username "{username}" already exists.')
        elif len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        else:
            user = User.objects.create_user(
                username=username,
                password=password,
                email=email,
                is_staff=is_staff,
            )
            # Assign selected keywords
            for kid in keyword_ids:
                try:
                    kw = Keyword.objects.get(pk=kid)
                    UserKeyword.objects.get_or_create(
                        user=user, keyword=kw,
                        defaults={'assigned_by': request.user}
                    )
                except Keyword.DoesNotExist:
                    pass

            kw_count = len(keyword_ids)
            messages.success(request, f'User "{username}" created with {kw_count} keyword(s).')
            return redirect('masters:create_user_view')

    all_users = User.objects.prefetch_related(
        'user_keywords__keyword'
    ).all().order_by('-date_joined')

    keywords = Keyword.objects.all()

    return render(request, 'masters/create_user.html', {
        'all_users': all_users,
        'keywords': keywords,
    })


# ─── USERS LIST WITH KEYWORD DISPLAY & EDIT ───────────────────────────────────

@login_required
@superuser_required
def users_list_view(request):
    """All users with their assigned keywords. Supports inline keyword edit."""
    all_users = User.objects.prefetch_related(
        'user_keywords__keyword'
    ).all().order_by('-date_joined')

    keywords = Keyword.objects.all()

    return render(request, 'masters/users_list.html', {
        'all_users': all_users,
        'keywords': keywords,
    })


@login_required
@superuser_required
@require_POST
def user_keywords_update_view(request, user_id):
    """Update keyword assignments for a user (AJAX)."""
    user = get_object_or_404(User, pk=user_id)

    try:
        data = json.loads(request.body)
        keyword_ids = [int(x) for x in data.get('keyword_ids', [])]
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid data.'}, status=400)

    # Remove all existing, re-add selected
    UserKeyword.objects.filter(user=user).delete()
    assigned = []
    for kid in keyword_ids:
        try:
            kw = Keyword.objects.get(pk=kid)
            UserKeyword.objects.create(user=user, keyword=kw, assigned_by=request.user)
            assigned.append({'id': kw.pk, 'name': kw.name, 'color': kw.color})
        except Keyword.DoesNotExist:
            pass

    return JsonResponse({'ok': True, 'keywords': assigned})