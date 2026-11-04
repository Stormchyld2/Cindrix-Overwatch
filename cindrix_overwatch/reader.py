"""A no-script page reader: turns a web page into plain text and a link list.

Nothing in the page runs. No scripts, no images, no cookies, no styles. That is the safe way to look at a page from a
place you do not know, and it is why this is a reader and not a full browser.
"""

from html.parser import HTMLParser
from urllib.parse import urljoin

SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "object", "embed", "head"}
BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer",
         "blockquote", "pre", "ul", "ol", "table"}


class _R(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.title, self.parts, self.links = base, "", [], []
        self.skip, self.in_title, self.href = 0, False, None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in SKIP and tag != "head":
            self.skip += 1
        if tag in BLOCK:
            self.parts.append("\n")
        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            u = urljoin(self.base, href) if href else ""
            self.href = u if u.lower().startswith(("http://", "https://")) else None

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in SKIP and tag != "head" and self.skip:
            self.skip -= 1
        if tag in BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self.href = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.skip:
            return
        t = " ".join(data.split())
        if not t:
            return
        self.parts.append(t + " ")
        if self.href and len(self.links) < 200:
            self.links.append((t[:100], self.href))


def html_to_text(html, base=""):
    """Returns (title, text, [(label, url), ...])."""
    r = _R(base)
    try:
        r.feed(html[:2_000_000])
    except Exception:
        pass
    text = "".join(r.parts)
    lines = [ln.strip() for ln in text.split("\n")]
    out, blank = [], 0
    for ln in lines:
        if ln:
            out.append(ln)
            blank = 0
        elif blank == 0 and out:
            out.append("")
            blank = 1
    seen, links = set(), []
    for label, url in r.links:
        if url not in seen:
            seen.add(url)
            links.append((label, url))
    return " ".join(r.title.split())[:200], "\n".join(out).strip(), links
