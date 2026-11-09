def format_price(cents):
    return f"${cents // 100}.{cents % 100}"


def format_total(cent_list):
    total = sum(cent_list)
    return f"${total // 100}.{total % 100}"
