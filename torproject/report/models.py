from django.db import models


class DarkwebArticle(models.Model):
    keyword    = models.TextField()
    title      = models.TextField(blank=True, null=True)
    url        = models.TextField()
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Tell Django to use the EXISTING table — don't create a new one
        managed  = False
        db_table = 'darkweb_articles'
        ordering = ['-scraped_at']
        unique_together = [('url', 'keyword')]   # ← matches the DB UNIQUE

    def __str__(self):
        return self.title or self.url


class DarkwebImage(models.Model):
    article      = models.ForeignKey(
        DarkwebArticle,
        on_delete=models.CASCADE,
        related_name='images',
        db_column='article_id',
    )
    image_path   = models.TextField(blank=True, null=True)
    image_type   = models.TextField(blank=True, null=True)
    original_src = models.TextField(blank=True, null=True)

    class Meta:
        managed  = False
        db_table = 'darkweb_images'

    def __str__(self):
        return self.image_path or str(self.id)


class DarkwebBlock(models.Model):
    article      = models.ForeignKey(
        DarkwebArticle,
        on_delete=models.CASCADE,
        related_name='blocks',
        db_column='article_id',
    )
    block_order  = models.IntegerField(blank=True, null=True)
    block_type   = models.TextField(blank=True, null=True)   # 'heading' | 'text' | 'image'
    text_content = models.TextField(blank=True, null=True)
    image        = models.ForeignKey(
        DarkwebImage,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='blocks',
        db_column='image_id',
    )

    class Meta:
        managed  = False
        db_table = 'darkweb_blocks'
        ordering = ['block_order']

    def __str__(self):
        return f"{self.block_type} — article {self.article_id}"
    
    
from django.db import models


class BlackMarketCategory(models.Model):

    name = models.TextField()
    url = models.TextField(unique=True)
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blackmarket_categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class BlackMarketProduct(models.Model):

    category = models.ForeignKey(
        BlackMarketCategory,
        on_delete=models.CASCADE,
        related_name="products",
        db_column="category_id"
    )

    title = models.TextField(blank=True, null=True)
    url = models.TextField(unique=True)

    price = models.TextField(blank=True, null=True)
    btc_price = models.TextField(blank=True, null=True)

    vendor = models.TextField(blank=True, null=True)
    vendor_rating = models.TextField(blank=True, null=True)

    shipping = models.TextField(blank=True, null=True)
    shipping_time = models.TextField(blank=True, null=True)

    description = models.TextField(blank=True, null=True)
    more_offers = models.TextField(blank=True, null=True)
    store_policies = models.TextField(blank=True, null=True)
    inquiries = models.TextField(blank=True, null=True)

    image_path = models.TextField(blank=True, null=True)

    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blackmarket_products"
        ordering = ["-scraped_at"]

    def __str__(self):
        return self.title or self.url