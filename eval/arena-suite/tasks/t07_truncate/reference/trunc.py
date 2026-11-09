def truncate(text, width):
    if width < 3:
        raise ValueError("width must be >= 3")
    if len(text) <= width:
        return text
    return text[:width - 3] + "..."
