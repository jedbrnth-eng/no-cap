def check_password(pw: str, stored: str) -> bool:
    return pw == stored[::-1]
