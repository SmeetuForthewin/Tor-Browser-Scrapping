
from masters.models import Keyword, UserKeyword
from report.models import DarkwebArticle   # adjust import if needed
from masters.models import UserArticleView

def notification_counts(request):
    if not request.user.is_authenticated:
        return {
            'total_new'         : 0,
            'new_counts_per_kw' : {},
            'all_notif_keywords': [],
            'bm_new_count'      : 0,   # ← added
        }

    user = request.user

    # keywords this user can see
    if user.is_superuser:
        keywords = list(Keyword.objects.all())
    else:
        kw_ids   = UserKeyword.objects.filter(user=user).values_list('keyword_id', flat=True)
        keywords = list(Keyword.objects.filter(pk__in=kw_ids))

    seen_ids = set(
        UserArticleView.objects.filter(user=user).values_list('article_id', flat=True)
    )

    per_kw = {}
    total  = 0
    for kw in keywords:
        new_cnt = DarkwebArticle.objects.filter(keyword=kw.name).exclude(pk__in=seen_ids).count()
        if new_cnt:
            per_kw[kw.pk] = new_cnt
            total         += new_cnt

    # ── Black Market new count ────────────────────────────────────────────────
    from report.models import BlackMarketProduct
    from masters.models import UserProductView

    bm_seen_ids = set(
        UserProductView.objects.filter(user=user).values_list('product_id', flat=True)
    )
    bm_new = BlackMarketProduct.objects.exclude(pk__in=bm_seen_ids).count()
    # ─────────────────────────────────────────────────────────────────────────

    return {
        'total_new'         : total,
        'new_counts_per_kw' : per_kw,
        'all_notif_keywords': keywords,
        'bm_new_count'      : bm_new,   # ← added
    }