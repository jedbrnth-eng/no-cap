def truncate(text, width):
    if len(text) <= width:
        return text
    return text[:width] + "..."
