# Records calls instead of touching a cache.
calls = []


def invalidate_cache_directly(path=None, url_params=False, user=True, request=None, multiple=False):
    calls.append({"path": path, "url_params": url_params, "user": user, "multiple": multiple})
