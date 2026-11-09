def page_count(total, per_page):
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    return total // per_page + 1


def page_slice(items, page, per_page):
    start = page * per_page
    return items[start:start + per_page]
