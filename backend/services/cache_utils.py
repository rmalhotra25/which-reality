"""Bounded in-memory caches.

Every in-memory cache in the app used to grow one entry per key
until the process restarted: TTLs were checked on read only and
expired entries were never evicted. On Render's free plan (512 MB)
that slow growth contributed to the Nov 10 2026 out-of-memory
restart that 502'd a lookup. Each cache now stores through
bounded_put, which drops expired entries first, then the oldest
entries until the cache is under its cap.
"""


def bounded_put(cache, key, value, *, now, ttl_seconds, max_entries):
    """Store (now, value) under key, evicting expired then oldest.

    `cache` maps key -> (timestamp, value). Entries older than
    ttl_seconds are dropped first. If the cache is still at or over
    max_entries, the oldest entries are dropped until there is room.
    Refreshing an existing key does not evict anything else.
    """
    for expired in [k for k, (ts, _v) in cache.items()
                    if now - ts >= ttl_seconds]:
        del cache[expired]
    if key in cache:
        del cache[key]
    while len(cache) >= max_entries:
        oldest = min(cache, key=lambda k: cache[k][0])
        del cache[oldest]
    cache[key] = (now, value)
