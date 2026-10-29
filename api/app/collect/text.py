"""Turn an HTML page into the plain text that quotes are checked against.

Both sides of a quote check go through `normalize`, so a quote copied from the rendered text matches
the page whatever its non-breaking spaces, curly quotes, or line breaks were.
"""

import re
import unicodedata
from html.parser import HTMLParser

# Elements whose text is never part of what a reader sees on the page.
SKIP = {"script", "style", "noscript", "svg", "template", "head", "iframe"}
# Elements that start a new line of text, so words from adjacent blocks are not glued together.
BLOCK = {
    "p", "div", "section", "article", "header", "footer", "main", "aside", "nav", "li", "ul", "ol",
    "table", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "br", "dt", "dd", "dl",
    "blockquote", "figcaption", "summary", "details", "form", "label", "option",
}

PUNCTUATION = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
    " ": " ", " ": " ", " ": " ", "​": "",
})


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP:
            self.skip_depth += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """The visible text of a page, one block per line, blank lines collapsed."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in "".join(parser.parts).split("\n"))
    return "\n".join(line for line in lines if line)


def normalize(text: str) -> str:
    """Fold the differences that are not the page's words: Unicode forms, quotes, dashes, spacing."""
    text = unicodedata.normalize("NFKC", text).translate(PUNCTUATION)
    return re.sub(r"\s+", " ", text).strip().casefold()
