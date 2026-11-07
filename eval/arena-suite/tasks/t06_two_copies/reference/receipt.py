def format_price(cents):
    return f"${cents // 100:,}.{cents % 100:02d}"


def format_total(cent_list):
    return format_price(sum(cent_list))
