def compare_versions(a, b):
    if a == b:
        return 0
    return -1 if a < b else 1
