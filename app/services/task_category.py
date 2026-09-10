import re


_URL_SCHEME_RE = re.compile(
    r"(?:^|[\s(/-])(?:https?|ftp):(?://)?",
    re.IGNORECASE,
)


def extract_task_category(text: str) -> str | None:
    """Return a title prefix before ``:``, unless the title starts with a URL."""
    prefix, separator, _ = text.partition(":")
    if not separator:
        return None
    # A URL may be embedded in a task title, e.g. "Изучить https:" or
    # "Импортировать скилл - https://...". In both cases the colon belongs
    # to the URL scheme, not to a user-defined category.
    if _URL_SCHEME_RE.search(text[: len(prefix) + 1]):
        return None
    category = prefix.strip()
    return category[:80] if category else None
