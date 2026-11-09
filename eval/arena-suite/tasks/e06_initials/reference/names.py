def initials(full_name):
    parts = full_name.replace("-", " ").split()
    return "".join(part[0].upper() for part in parts)
