from django.core.paginator import Paginator


def paginate(request, queryset, per_page=40):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("seite"))


def int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
