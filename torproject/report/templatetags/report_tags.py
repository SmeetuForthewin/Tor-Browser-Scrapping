from django import template
from django.templatetags.static import static

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """{{ my_dict|get_item:key }} — works with both string and int keys."""
    if dictionary is None:
        return None
    # try as-is first, then coerce
    val = dictionary.get(key)
    if val is None:
        try:
            val = dictionary.get(int(key))
        except (TypeError, ValueError):
            pass
    return val


@register.filter
def static_url(image_path):
    """
    Convert DB-stored relative path to a /static/ URL.
    DB stores:  darkweb_images/india/article_1/img_1.jpg
    Returns:    /static/darkweb_images/india/article_1/img_1.jpg
    """
    if not image_path:
        return ''
    path = str(image_path).replace('\\', '/').lstrip('/')
    return static(path)


@register.filter
def new_article_count(articles):
    """
    Returns the number of articles in a list that have  .is_new == True.
    Usage:  {% with cnt=articles|new_article_count %}
    """
    if not articles:
        return 0
    return sum(1 for a in articles if getattr(a, 'is_new', False))