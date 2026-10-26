from django.db import models
from django.contrib.auth.models import User


class Keyword(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#0ea5e9')  # hex color for tag display
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='created_keywords'
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UserKeyword(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_keywords')
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, related_name='user_keywords')
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='assigned_keywords'
    )

    class Meta:
        unique_together = ('user', 'keyword')
        ordering = ['keyword__name']

    def __str__(self):
        return f'{self.user.username} → {self.keyword.name}'
    
    
    # ─────────────────────────────────────────────────────────────────
# ADD THIS MODEL to your existing masters/models.py (bottom of file)
# Then run:  python manage.py makemigrations && python manage.py migrate
# ─────────────────────────────────────────────────────────────────

from django.db import models
from django.contrib.auth.models import User


class UserArticleView(models.Model):
    """
    Tracks which DarkwebArticle PKs each user has already seen.

    Logic:
      - Any article NOT in this table for a given user  →  "NEW"  (show badge)
      - When a user opens the Report page, all articles they can see
        are bulk-inserted here  →  next visit those articles are no longer new
      - The notification bell count  =  articles accessible to the user
        that are NOT yet in this table
    """
    user          = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='viewed_articles'
    )
    article_id    = models.IntegerField()   # mirrors DarkwebArticle.pk (unmanaged table)
    keyword       = models.ForeignKey(
        'masters.Keyword',
        on_delete=models.CASCADE,
        related_name='viewed_articles',
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'article_id')
        ordering        = ['-first_seen_at']
        db_table        = 'report_userarticleview'

    def __str__(self):
        return f'{self.user.username} → article {self.article_id}'
    
    
    
class UserProductView(models.Model):
    """
    Tracks which BlackMarketProduct PKs each user has already seen.
    Any product NOT in this table for a given user  →  "NEW" (show badge)
    When a user opens the Black Market page, all visible products are
    bulk-inserted here  →  next visit those products are no longer new.
    """
    user          = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='viewed_products'
    )
    product_id    = models.IntegerField()   # mirrors BlackMarketProduct.pk
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product_id')
        ordering        = ['-first_seen_at']
        db_table        = 'report_userproductview'

    def __str__(self):
        return f'{self.user.username} → product {self.product_id}'
