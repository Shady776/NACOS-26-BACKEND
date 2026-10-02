"""Server-side HTML sanitizing (second layer behind DOMPurify in the browser)."""
from typing import Optional

import nh3

# Formatting the rich-text editor produces. No scripts, iframes, forms,
# inline event handlers or style attributes.
_ALLOWED_TAGS = {
    "p", "br", "hr", "div", "span", "blockquote", "pre", "code",
    "strong", "b", "em", "i", "u", "s", "sub", "sup",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tr", "th", "td", "a",
}
_ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
_ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def sanitize_html(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return nh3.clean(
        value,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
