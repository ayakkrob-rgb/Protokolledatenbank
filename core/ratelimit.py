from django.core.cache import cache


def allow(key, limit, window_seconds):
    """Einfache Begrenzung von Versuchen (z. B. Login) pro Schlüssel und Zeitfenster.

    Gibt ``False`` zurück, wenn das Limit bereits erreicht ist.
    """
    cache_key = f"ratelimit:{key}"
    if cache.add(cache_key, 1, window_seconds):
        return True
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, window_seconds)
        return True
    return count <= limit


def reset(key):
    cache.delete(f"ratelimit:{key}")
