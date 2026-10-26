from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils import timezone
from django.conf import settings

from masters.models import UserKeyword
from report.models import DarkwebArticle, DarkwebBlock, DarkwebImage

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, PageBreak, Image as RLImage
)
from reportlab.pdfgen import canvas as pdfcanvas
from pypdf import PdfWriter, PdfReader
import io
import os
from datetime import datetime
from masters.models import Keyword, UserKeyword
from .models import DarkwebArticle          # adjust import path if needed
from masters.models import UserArticleView                 # the new model above

def get_new_counts_for_user(user):
    """
    Returns a dict  { keyword_pk: new_count, ... }
    and a total int  total_new_count
    for the notification bell.
    """
    # keywords this user can see
    kw_ids = UserKeyword.objects.filter(user=user).values_list('keyword_id', flat=True)
    if user.is_superuser:
        kw_ids = Keyword.objects.values_list('pk', flat=True)

    keywords = Keyword.objects.filter(pk__in=kw_ids)

    # article IDs the user has already seen
    seen_ids = set(
        UserArticleView.objects.filter(user=user).values_list('article_id', flat=True)
    )

    per_kw   = {}
    total    = 0
    for kw in keywords:
        articles = DarkwebArticle.objects.filter(keyword=kw.name)
        new_cnt  = articles.exclude(pk__in=seen_ids).count()
        if new_cnt:
            per_kw[kw.pk] = new_cnt
            total         += new_cnt

    return per_kw, total

def hex_to_color(hex_str, default="#2563eb"):
    try:
        h = hex_str.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return colors.Color(r / 255, g / 255, b / 255)
    except Exception:
        return colors.HexColor(default)

@login_required
def report_view(request):
    user = request.user

    # ── 1. Resolve which keywords this user can see ──────────────────────────
    if user.is_superuser:
        all_keywords = Keyword.objects.all()
    else:
        kw_ids       = UserKeyword.objects.filter(user=user).values_list('keyword_id', flat=True)
        all_keywords = Keyword.objects.filter(pk__in=kw_ids)

    # ── 2. Filter toggle  (?keyword=<pk>  or  ?keyword=all  or nothing) ──────
    selected_kw_pk = request.GET.get('keyword', 'all')
    if selected_kw_pk != 'all':
        try:
            selected_kw_pk = int(selected_kw_pk)
            keyword_objects = all_keywords.filter(pk=selected_kw_pk)
        except (ValueError, TypeError):
            keyword_objects = all_keywords
            selected_kw_pk  = 'all'
    else:
        keyword_objects = all_keywords

    # ── 3. Build articles_by_keyword dict & collect NEW article IDs ──────────
    seen_ids = set(
        UserArticleView.objects.filter(user=user).values_list('article_id', flat=True)
    )

    articles_by_keyword = {}
    new_ids_this_load   = []   # will be marked as seen after rendering

    for kw in keyword_objects:
        arts = list(DarkwebArticle.objects.filter(keyword=kw.name))
        # annotate each article with .is_new
        for art in arts:
            art.is_new = art.pk not in seen_ids
            if art.is_new:
                new_ids_this_load.append((user, art.pk, kw))
        articles_by_keyword[kw] = arts

    total_articles = sum(len(v) for v in articles_by_keyword.values())

    # ── 4. Mark all currently-visible NEW articles as seen ───────────────────
    #       (bulk_create with ignore_conflicts so duplicates are skipped safely)
    if new_ids_this_load:
        UserArticleView.objects.bulk_create(
            [
                UserArticleView(user=u, article_id=aid, keyword=kw)
                for u, aid, kw in new_ids_this_load
            ],
            ignore_conflicts=True,
        )

    # ── 5. Notification counts (for the bell in base template) ───────────────
    #       NOTE: we compute BEFORE marking seen so the bell reflects reality
    #       on THIS load — recalc after marking means bell goes to 0 immediately.
    #       If you want the bell to reset on visit, compute AFTER bulk_create.
    new_counts_per_kw, total_new = get_new_counts_for_user(user)
    # Re-compute after mark-as-seen so bell clears on this visit:
    new_counts_per_kw, total_new = get_new_counts_for_user(user)

    context = {
        'keyword_objects'   : list(keyword_objects),
        'all_keywords'      : list(all_keywords),          # for the toggle UI
        'articles_by_keyword': articles_by_keyword,
        'total_articles'    : total_articles,
        'generated_at'      : timezone.now(),
        'selected_kw_pk'    : selected_kw_pk,             # 'all' or int pk
        # notification data (also available via context processor if preferred)
        'new_counts_per_kw' : new_counts_per_kw,
        'total_new'         : total_new,
    }
    return render(request, 'report/report.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# COVER PAGE — white/light, matches the rest of the report style
# ─────────────────────────────────────────────────────────────────────────────
def build_cover_pdf(username, keyword_objects, articles_by_keyword):
    buf = io.BytesIO()
    width, height = A4
    c = pdfcanvas.Canvas(buf, pagesize=A4)

    MARGIN = 2.2 * cm

    C_BLUE     = colors.HexColor("#2563eb")
    C_DARK     = colors.HexColor("#0f172a")
    C_TEXT2    = colors.HexColor("#334155")
    C_MUTED    = colors.HexColor("#64748b")
    C_SUBTLE   = colors.HexColor("#94a3b8")
    C_BG       = colors.HexColor("#f1f5f9")
    C_BORDER   = colors.HexColor("#e2e8f0")
    C_BLUE_LT  = colors.HexColor("#eff6ff")
    C_BLUE_MID = colors.HexColor("#bfdbfe")

    # White background
    c.setFillColor(colors.white)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    # Top blue bar (full width)
    c.setFillColor(C_BLUE)
    c.rect(0, height - 1.1 * cm, width, 1.1 * cm, fill=1, stroke=0)

    # "TOR PANEL" in the top bar
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, height - 0.75 * cm, "TOR PANEL")

    # Date top-right in bar
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.Color(1, 1, 1, 0.75))
    c.drawRightString(width - MARGIN, height - 0.75 * cm,
                      datetime.now().strftime("%Y-%m-%d  %H:%M UTC"))

    # ── Hero section ──────────────────────────────────────────────────────
    hero_y = height - 1.1 * cm  # just below top bar

    # Light blue hero background
    hero_h = 7.5 * cm
    c.setFillColor(C_BLUE_LT)
    c.rect(0, hero_y - hero_h, width, hero_h, fill=1, stroke=0)

    # Hero bottom border
    c.setStrokeColor(C_BLUE_MID)
    c.setLineWidth(1)
    c.line(0, hero_y - hero_h, width, hero_y - hero_h)

    # Small label above title
    label_y = hero_y - 1.6 * cm
    c.setFillColor(C_BLUE)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(MARGIN, label_y, "INTELLIGENCE REPORT")

    # Thin blue underline under label
    c.setStrokeColor(C_BLUE)
    c.setLineWidth(1.5)
    c.line(MARGIN, label_y - 0.15 * cm, MARGIN + 3.5 * cm, label_y - 0.15 * cm)

    # Big title
    c.setFillColor(C_DARK)
    c.setFont("Helvetica-Bold", 38)
    c.drawString(MARGIN, hero_y - 3.2 * cm, "TOR Panel")

    # Subtitle
    c.setFillColor(C_MUTED)
    c.setFont("Helvetica", 13)
    c.drawString(MARGIN, hero_y - 4.3 * cm, "Dark Web Monitoring & Intelligence")

    # Blue accent dot before subtitle
    c.setFillColor(C_BLUE)
    c.circle(MARGIN - 0.35 * cm, hero_y - 4.15 * cm, 0.07 * cm, fill=1, stroke=0)

    # ── Meta cards row ────────────────────────────────────────────────────
    total_arts = sum(len(v) for v in articles_by_keyword.values())
    meta_items = [
        ("Operator",  username),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Keywords",  str(len(keyword_objects))),
        ("Articles",  str(total_arts)),
    ]
    cards_y    = hero_y - hero_h - 1.4 * cm
    usable_w   = width - 2 * MARGIN
    card_w     = usable_w / len(meta_items)
    card_h     = 1.4 * cm
    card_gap   = 0.2 * cm

    for i, (label, value) in enumerate(meta_items):
        x = MARGIN + i * card_w
        cw = card_w - card_gap

        # Card background
        c.setFillColor(C_BG)
        c.roundRect(x, cards_y - card_h, cw, card_h, 0.2 * cm, fill=1, stroke=0)
        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.5)
        c.roundRect(x, cards_y - card_h, cw, card_h, 0.2 * cm, fill=0, stroke=1)

        # Blue left accent
        c.setFillColor(C_BLUE)
        c.roundRect(x, cards_y - card_h, 0.22 * cm, card_h, 0.1 * cm, fill=1, stroke=0)

        # Label
        c.setFillColor(C_SUBTLE)
        c.setFont("Helvetica", 7)
        c.drawString(x + 0.45 * cm, cards_y - 0.42 * cm, label.upper())

        # Value
        c.setFillColor(C_DARK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 0.45 * cm, cards_y - 0.95 * cm, value)

    # ── Divider ───────────────────────────────────────────────────────────
    div_y = cards_y - card_h - 1.0 * cm
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.5)
    c.line(MARGIN, div_y, width - MARGIN, div_y)

    # ── Keywords section ──────────────────────────────────────────────────
    kw_title_y = div_y - 0.55 * cm
    c.setFillColor(C_DARK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, kw_title_y, "Monitored Keywords")

    c.setFillColor(C_SUBTLE)
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN, kw_title_y - 0.45 * cm,
                 f"{len(keyword_objects)} keyword{'s' if len(keyword_objects) != 1 else ''} "
                 f"assigned to this operator")

    # Keyword chips
    chip_h     = 0.65 * cm
    chip_gap_x = 0.2 * cm
    chip_gap_y = 0.2 * cm
    x_cursor   = MARGIN
    y_cursor   = kw_title_y - 1.2 * cm
    row_max_x  = width - MARGIN

    for kw in keyword_objects:
        kw_color = hex_to_color(kw.color)
        count    = len(articles_by_keyword.get(kw, []))
        label    = f"  {kw.name}  ·  {count}  "
        chip_w   = len(label) * 5.2 + 0.3 * cm

        if x_cursor + chip_w > row_max_x:
            x_cursor  = MARGIN
            y_cursor -= chip_h + chip_gap_y

        if y_cursor < 2.5 * cm:
            break

        # Chip bg (light tint)
        c.setFillColor(colors.Color(kw_color.red, kw_color.green, kw_color.blue, 0.08))
        c.roundRect(x_cursor, y_cursor - 0.05 * cm, chip_w, chip_h,
                    0.22 * cm, fill=1, stroke=0)
        # Chip border
        c.setStrokeColor(colors.Color(kw_color.red, kw_color.green, kw_color.blue, 0.35))
        c.setLineWidth(0.7)
        c.roundRect(x_cursor, y_cursor - 0.05 * cm, chip_w, chip_h,
                    0.22 * cm, fill=0, stroke=1)
        # Dot
        c.setFillColor(kw_color)
        c.circle(x_cursor + 0.4 * cm, y_cursor + chip_h / 2 - 0.05 * cm,
                 0.07 * cm, fill=1, stroke=0)
        # Text
        c.setFillColor(kw_color)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(x_cursor + 0.6 * cm, y_cursor + 0.13 * cm,
                     f"{kw.name}  ·  {count}")

        x_cursor += chip_w + chip_gap_x

    # ── Bottom bar ────────────────────────────────────────────────────────
    c.setFillColor(C_BG)
    c.rect(0, 0, width, 1.3 * cm, fill=1, stroke=0)
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.5)
    c.line(0, 1.3 * cm, width, 1.3 * cm)

    c.setFillColor(C_SUBTLE)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN, 0.5 * cm, "TOR Panel  ·  Automated Intelligence Collection")
    c.setFont("Courier", 8)
    ref = f"REF: TOR-{datetime.now().strftime('%Y%m%d')}-{username[:6].upper()}"
    c.drawRightString(width - MARGIN, 0.5 * cm, ref)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

def notification_counts(request):
    if not request.user.is_authenticated:
        return {'total_new': 0, 'new_counts_per_kw': {}, 'bm_new_count': 0}
    from masters.models import  UserProductView

    from report.models import BlackMarketProduct
    _, total_new = get_new_counts_for_user(request.user)

    seen_ids  = set(UserProductView.objects.filter(user=request.user).values_list('product_id', flat=True))
    bm_new    = BlackMarketProduct.objects.exclude(pk__in=seen_ids).count()

    return {
        'total_new':        total_new,
        'bm_new_count':     bm_new,
        'new_counts_per_kw': {},
    }

# ─────────────────────────────────────────────────────────────────────────────
# PDF DOWNLOAD VIEW
# ─────────────────────────────────────────────────────────────────────────────
@login_required
def report_pdf_view(request):
    user = request.user

    user_keywords = UserKeyword.objects.filter(user=user).select_related('keyword')
    keyword_objects = [uk.keyword for uk in user_keywords]

    kw_filter = request.GET.get('keyword')
    if kw_filter:
        keyword_objects = [kw for kw in keyword_objects if str(kw.pk) == kw_filter]

    articles_by_keyword = {}
    for kw in keyword_objects:
        arts = DarkwebArticle.objects.filter(keyword=kw.name).prefetch_related(
            'blocks__image'
        ).order_by('-scraped_at')
        articles_by_keyword[kw] = list(arts)

    STATIC_DIR = str(settings.STATICFILES_DIRS[0])
    PAGE_W, PAGE_H = A4
    MARGIN    = 2.2 * cm
    CONTENT_W = PAGE_W - 2 * MARGIN

    C_BLUE   = colors.HexColor("#2563eb")
    C_DARK   = colors.HexColor("#0f172a")
    C_TEXT2  = colors.HexColor("#334155")
    C_MUTED  = colors.HexColor("#64748b")
    C_SUBTLE = colors.HexColor("#94a3b8")
    C_BG     = colors.HexColor("#f1f5f9")
    C_BORDER = colors.HexColor("#e2e8f0")
    C_WHITE  = colors.white

    def ms(name, **kw):
        return ParagraphStyle(name, **kw)

    body_s   = ms('Body', fontName='Helvetica', fontSize=10,
                  leading=15, textColor=C_TEXT2, spaceAfter=5)
    head_s   = ms('Hd', fontName='Helvetica-Bold', fontSize=11,
                  leading=16, textColor=C_DARK, spaceBefore=6, spaceAfter=3)
    cap_s    = ms('Cap', fontName='Courier', fontSize=8,
                  leading=11, textColor=C_SUBTLE, spaceAfter=4)
    nodata_s = ms('ND', fontName='Helvetica', fontSize=10, leading=15,
                  textColor=C_SUBTLE, alignment=TA_CENTER, spaceAfter=8)

    content_buf = io.BytesIO()
    doc = SimpleDocTemplate(
        content_buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=f"TOR Report — {user.username}",
        author="TOR Panel",
    )

    story = []

    # TOC
    story.append(Paragraph("Contents", ms(
        'toc_h', fontName='Helvetica-Bold', fontSize=20, leading=26,
        textColor=C_DARK, spaceAfter=6)))
    story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_BORDER, spaceAfter=14))

    for i, kw in enumerate(keyword_objects, 1):
        count    = len(articles_by_keyword.get(kw, []))
        kw_color = hex_to_color(kw.color)
        row = Table([[
            Paragraph(f"<b>{i:02d}</b>",
                      ms(f'tni{i}', fontName='Courier', fontSize=10, textColor=C_SUBTLE)),
            Paragraph(f"<b>{kw.name}</b>",
                      ms(f'tnk{i}', fontName='Helvetica-Bold', fontSize=11, textColor=kw_color)),
            Paragraph(f"{count} article{'s' if count != 1 else ''}",
                      ms(f'tnc{i}', fontName='Helvetica', fontSize=10, textColor=C_MUTED)),
        ]], colWidths=[1 * cm, CONTENT_W - 4 * cm, 3 * cm])
        row.setStyle(TableStyle([
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LINEBELOW',     (0, 0), (-1, -1), 0.3, C_BORDER),
        ]))
        story.append(row)

    story.append(PageBreak())

    for kw_idx, kw in enumerate(keyword_objects):
        articles = articles_by_keyword.get(kw, [])
        kw_color = hex_to_color(kw.color)

        hdr = Table([[
            Paragraph(f"<b>{kw.name}</b>",
                      ms(f'sh{kw.pk}', fontName='Helvetica-Bold', fontSize=16, textColor=C_WHITE)),
            Paragraph(f"{len(articles)} article{'s' if len(articles) != 1 else ''}",
                      ms(f'sc{kw.pk}', fontName='Courier', fontSize=9,
                         textColor=colors.Color(1, 1, 1, 0.6), alignment=TA_RIGHT)),
        ]], colWidths=[CONTENT_W * 0.7, CONTENT_W * 0.3])
        hdr.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), kw_color),
            ('TOPPADDING',    (0, 0), (-1, -1), 14),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
            ('LEFTPADDING',   (0, 0), (-1, -1), 20),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 20),
            ('ROUNDEDCORNERS', [8]),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(KeepTogether([hdr, Spacer(1, 0.4 * cm)]))

        if kw.description:
            story.append(Paragraph(kw.description, cap_s))
            story.append(Spacer(1, 0.2 * cm))

        if not articles:
            story.append(Paragraph("No articles found for this keyword.", nodata_s))
            story.append(Spacer(1, 0.4 * cm))
            continue

        for art_idx, article in enumerate(articles):
            art_num   = f"{kw_idx + 1}.{art_idx + 1}"
            title_row = Table([[Paragraph(
                f"<font color='#94a3b8'>{art_num}</font>  <b>{article.title or 'Untitled'}</b>",
                ms(f'at{article.id}', fontName='Helvetica-Bold',
                   fontSize=11, textColor=C_DARK, leading=16)
            )]], colWidths=[CONTENT_W])
            title_row.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, -1), C_BG),
                ('LEFTPADDING',   (0, 0), (-1, -1), 14),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
                ('TOPPADDING',    (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('LINERIGHT',     (0, 0), (0, -1), 3, kw_color),
                ('ROUNDEDCORNERS', [6]),
            ]))

            meta_row = Table([[
                Paragraph(
                    f"{article.url[:90]}{'...' if len(article.url) > 90 else ''}",
                    ms(f'url{article.id}', fontName='Courier',
                       fontSize=7.5, textColor=C_SUBTLE, leading=11)
                ),
                Paragraph(
                    article.scraped_at.strftime("%Y-%m-%d %H:%M") if article.scraped_at else "-",
                    ms(f'dt{article.id}', fontName='Courier', fontSize=7.5,
                       textColor=C_SUBTLE, leading=11, alignment=TA_RIGHT)
                ),
            ]], colWidths=[CONTENT_W * 0.72, CONTENT_W * 0.28])
            meta_row.setStyle(TableStyle([
                ('TOPPADDING',    (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))

            cblocks = []
            try:
                for block in article.blocks.order_by('block_order'):
                    if block.block_type == 'heading' and block.text_content:
                        cblocks.append(Paragraph(block.text_content, head_s))
                    elif block.block_type == 'text' and block.text_content:
                        txt = block.text_content[:800] + ("..." if len(block.text_content) > 800 else "")
                        cblocks.append(Paragraph(txt, body_s))
                    elif block.block_type == 'image' and block.image:
                        rel  = str(block.image.image_path).replace('\\', '/').lstrip('/')
                        absp = os.path.join(STATIC_DIR, rel)
                        if os.path.isfile(absp):
                            try:
                                img = RLImage(absp)
                                max_w, max_h = CONTENT_W - cm, 5 * cm
                                ratio = img.imageWidth / img.imageHeight
                                if img.imageWidth > max_w:
                                    img.drawWidth  = max_w
                                    img.drawHeight = max_w / ratio
                                if img.drawHeight > max_h:
                                    img.drawHeight = max_h
                                    img.drawWidth  = max_h * ratio
                                cblocks += [Spacer(1, 0.2 * cm), img,
                                            Paragraph(os.path.basename(absp), cap_s)]
                            except Exception:
                                pass
            except Exception:
                pass

            if not cblocks:
                cblocks.append(Paragraph("No content extracted for this article.", cap_s))

            grp = [Spacer(1, 0.25 * cm), title_row, meta_row, Spacer(1, 0.15 * cm),
                   *cblocks,
                   Spacer(1, 0.3 * cm),
                   HRFlowable(width=CONTENT_W, thickness=0.3, color=C_BORDER),
                   Spacer(1, 0.15 * cm)]
            story.append(KeepTogether(grp[:4]))
            for item in grp[4:]:
                story.append(item)

        story.append(PageBreak())

    ft = Table([[Paragraph(
        f"TOR Panel Intelligence Report &nbsp;·&nbsp; Operator: <b>{user.username}</b>"
        f" &nbsp;·&nbsp; {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        ms('foot', fontName='Helvetica', fontSize=9,
           textColor=C_SUBTLE, alignment=TA_CENTER)
    )]], colWidths=[CONTENT_W])
    ft.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LINEABOVE',     (0, 0), (-1, -1), 0.5, C_BORDER),
    ]))
    story.append(Spacer(1, 1 * cm))
    story.append(ft)

# ── Page → keyword tracker (uses ActionFlowable which fires during draw) ──
    page_kw_map = {}
    current_kw_holder = ['']   # mutable container so closure can mutate it

    from reportlab.platypus.flowables import Flowable

    class KwPageMarker(Flowable):
        """Zero-size flowable; fires during draw to record keyword for this page."""
        def __init__(self, kw_name):
            Flowable.__init__(self)
            self.kw_name = kw_name
            self.width  = 0
            self.height = 0

        def draw(self):
            current_kw_holder[0] = self.kw_name
            # record page → kw (canv and doc are available as self.canv)
            try:
                page_kw_map[self.canv.getPageNumber()] = self.kw_name
            except Exception:
                pass

        def wrap(self, availWidth, availHeight):
            return 0, 0

    # Inject a KwPageMarker before every keyword section header (KeepTogether)
    story_with_markers = []
    kw_index = 0
    for item in story:
        if isinstance(item, KeepTogether) and kw_index < len(keyword_objects):
            # peek inside to confirm it's the coloured keyword header
            inner = getattr(item, '_content', None) or getattr(item, 'content', [])
            if inner and isinstance(inner[0], Table):
                story_with_markers.append(KwPageMarker(keyword_objects[kw_index].name))
                kw_index += 1
        story_with_markers.append(item)

    def on_page(canv, doc):
        canv.saveState()

        # ── Header (page 3+ only = content pages after cover+TOC) ──
        if doc.page >= 3:
            # Walk back to find the most recent keyword recorded so far
            current_kw = None
            for p in range(doc.page, 0, -1):
                if p in page_kw_map:
                    current_kw = page_kw_map[p]
                    break

            if current_kw:
                # Thin separator line below header area
                canv.setStrokeColor(C_BORDER)
                canv.setLineWidth(0.5)
                canv.line(MARGIN, PAGE_H - 0.9 * cm, PAGE_W - MARGIN, PAGE_H - 0.9 * cm)

                # "TOR Panel" in blue
                canv.setFillColor(C_BLUE)
                canv.setFont('Helvetica-Bold', 8)
                canv.drawString(MARGIN, PAGE_H - 0.65 * cm, "TOR Panel")

                # separator dot
                canv.setFillColor(C_SUBTLE)
                canv.setFont('Helvetica', 8)
                canv.drawString(MARGIN + 3.8 * cm, PAGE_H - 0.65 * cm, "·")

                # Keyword name in keyword color (use dark as fallback)
                canv.setFillColor(C_DARK)
                canv.setFont('Helvetica-Bold', 8)
                canv.drawString(MARGIN + 4.4 * cm, PAGE_H - 0.65 * cm, current_kw)

        # ── Footer ──
        canv.setFont('Helvetica', 8)
        canv.setFillColor(C_SUBTLE)
        canv.drawRightString(PAGE_W - MARGIN, 1.0 * cm, f"Page {doc.page}")
        canv.setFillColor(C_BLUE)
        canv.drawString(MARGIN, 1.0 * cm, "TOR Panel")

        canv.restoreState()

    # Increase top margin so header text doesn't overlap content
    doc.topMargin    = MARGIN + 0.6 * cm
    doc.bottomMargin = MARGIN + 0.3 * cm

    doc.build(story_with_markers, onFirstPage=on_page, onLaterPages=on_page)
    content_buf.seek(0)

    cover_buf = build_cover_pdf(user.username, keyword_objects, articles_by_keyword)

    writer = PdfWriter()
    for page in PdfReader(cover_buf).pages:
        writer.add_page(page)
    for page in PdfReader(content_buf).pages:
        writer.add_page(page)

    final_buf = io.BytesIO()
    writer.write(final_buf)
    final_buf.seek(0)

    fname = f"tor_report_{user.username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    response = HttpResponse(final_buf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response






import json
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.templatetags.static import static
import posixpath
def get_new_product_counts(user):
    """
    Returns a dict  { category_pk: new_count, ... }
    and a total int  total_new_products
    for the Black Market notification badge.
    """
    from report.models import BlackMarketProduct, UserProductView

    seen_ids = set(
        UserProductView.objects.filter(user=user).values_list('product_id', flat=True)
    )

    all_products = BlackMarketProduct.objects.all()
    total_new    = all_products.exclude(pk__in=seen_ids).count()

    return total_new
def clean_image_url(path):
    if not path:
        return ''
    # path in DB is like "black_market/filename.jpg"
    # static files live at  static/black_market/filename.jpg
    path = path.lstrip('/')
    if path.startswith('static/'):
        path = path[7:]
    return f'/static/{path}'

@login_required
def black_market(request):
    from report.models import BlackMarketCategory, BlackMarketProduct
    from masters.models import UserProductView   # ← import the new model

    categories   = list(BlackMarketCategory.objects.all())
    all_products = list(BlackMarketProduct.objects.select_related('category').all())

    total_categories = len(categories)
    total_products   = len(all_products)

    # ── Track new / seen ─────────────────────────────────────────────────────
    seen_ids = set(
        UserProductView.objects.filter(user=request.user)
        .values_list('product_id', flat=True)
    )

    new_product_ids = []
    for p in all_products:
        p.is_new = p.pk not in seen_ids      # annotate the object
        if p.is_new:
            new_product_ids.append(p.pk)

    total_new_products = len(new_product_ids)

    # Mark all new products as seen (so next visit clears them)
    if new_product_ids:
        UserProductView.objects.bulk_create(
            [UserProductView(user=request.user, product_id=pid) for pid in new_product_ids],
            ignore_conflicts=True,
        )

    # ── Build JSON blob keyed by product pk for fast JS lookup ───────────────
    products_json = {}
    for p in all_products:
        products_json[p.pk] = {
            'pk':            p.pk,
            'title':         p.title or '',
            'url':           p.url   or '',
            'price':         p.price or '',
            'btc_price':     p.btc_price or '',
            'vendor':        p.vendor or '',
            'vendor_rating': p.vendor_rating or '',
            'shipping':      p.shipping or '',
            'shipping_time': p.shipping_time or '',
            'description':   p.description or '',
            'more_offers':   p.more_offers or '',
            'store_policies':p.store_policies or '',
            'inquiries':     p.inquiries or '',
            'image_path':    clean_image_url(p.image_path),
            'category_name': p.category.name if p.category else '',
            'category_id':   p.category_id,
            'scraped_at':    p.scraped_at.strftime('%Y-%m-%d %H:%M') if p.scraped_at else '',
            'is_new':        p.is_new,        # ← pass to JS
        }

    context = {
        'categories':          categories,
        'all_products':        all_products,
        'total_categories':    total_categories,
        'total_products':      total_products,
        'total_new_products':  total_new_products,   # ← for the red chip in bar
        'generated_at':        timezone.now(),
        'products_json':       json.dumps(products_json, ensure_ascii=False, default=str),
    }
    return render(request, 'report/black_market.html', context)