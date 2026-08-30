#!/usr/bin/env python3
"""
Command-line chapter scraper.

Fetches chapter content from a site with URL pattern:
    https://<SITE_DOMAIN>/<page-name>/<chapter-name>.html

Content is read from <div id="chapter-content"> (paragraphs may be nested
inside sub-divs). Each chapter is saved as both .txt and .epub under:
    <page-name>/<chapter-name>/

Usage:
    python webscraper.py
        Interactive mode. Uses saved page-name if available (else prompts
        for it), always prompts for chapter-name.

    python webscraper.py <page-name> <chapter-name>
        Non-interactive start. Both are required together. Saves
        page-name as the new default.

    python webscraper.py --clear-default-page
        Clears the saved default page-name.

    python webscraper.py --save-till <chapter-name> <do-till>
        Starting at <chapter-name> (using the saved default page-name),
        follows the "next chapter" link <do-till> times, saving every
        chapter along the way without asking for confirmation.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from ebooklib import epub
except ImportError:
    print("Missing dependency 'ebooklib'. Install with: pip install ebooklib")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# TODO: set this to the real site domain (no scheme, no trailing slash).
SITE_DOMAIN = "example.com"

CONFIG_DIR = Path.home() / ".config" / "webscraper"
CONFIG_FILE = CONFIG_DIR / "config.json"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_default_page_name():
    return load_config().get("page_name")


def set_default_page_name(page_name):
    config = load_config()
    config["page_name"] = page_name
    save_config(config)


def clear_default_page_name():
    config = load_config()
    if "page_name" in config:
        del config["page_name"]
        save_config(config)
        print("Default page-name cleared.")
    else:
        print("No default page-name was set.")


# ---------------------------------------------------------------------------
# Fetching / parsing
# ---------------------------------------------------------------------------

def build_url(page_name, chapter_name):
    return f"https://{SITE_DOMAIN}/{page_name}/{chapter_name}.html"


def fetch_soup(url):
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_title(soup, fallback):
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return fallback


def extract_paragraphs(soup):
    content_div = soup.find("div", id="chapter-content")
    if content_div is None:
        raise ValueError(
            "Could not find <div id=\"chapter-content\"> on this page. "
            "The site's markup may have changed."
        )
    # find_all searches all descendants, so paragraphs nested inside
    # sub-divs are still picked up.
    paragraph_tags = content_div.find_all("p")
    paragraphs = [p.get_text(strip=True) for p in paragraph_tags]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        raise ValueError("No non-empty <p> tags found inside #chapter-content.")
    return paragraphs


def find_nav_url(soup, base_url, anchor_id):
    """Return absolute URL for <a id="anchor_id"> if present, else None."""
    a_tag = soup.find("a", id=anchor_id)
    if a_tag is None or not a_tag.get("href"):
        return None
    return urljoin(base_url, a_tag["href"])


def parse_page_and_chapter_from_url(url):
    """Extract (page-name, chapter-name) from a URL matching our pattern."""
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) < 2 or not parts[-1].endswith(".html"):
        return None, None
    chapter_name = parts[-1][: -len(".html")]
    page_name = parts[-2]
    return page_name, chapter_name


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def sanitize_name(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def txt_dir_for(page_name):
    return Path(sanitize_name(page_name)) / "allchaptersarchivetxt"


def epub_dir_for(page_name):
    return Path(sanitize_name(page_name)) / "allchaptersarchive"


def save_txt(out_dir, chapter_name, title, paragraphs):
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"{sanitize_name(chapter_name)}.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        f.write(title + "\n\n")
        f.write("\n\n".join(paragraphs))
    return txt_path


def save_epub(out_dir, chapter_name, title, paragraphs):
    out_dir.mkdir(parents=True, exist_ok=True)
    epub_path = out_dir / f"{sanitize_name(chapter_name)}.epub"

    book = epub.EpubBook()
    book.set_identifier(sanitize_name(chapter_name))
    book.set_title(title)
    book.set_language("en")

    body_html = "".join(f"<p>{p}</p>" for p in paragraphs)
    chapter = epub.EpubHtml(
        title=title, file_name="chapter.xhtml", lang="en"
    )
    chapter.content = f"<h1>{title}</h1>{body_html}"

    book.add_item(chapter)
    book.toc = (epub.Link("chapter.xhtml", title, "chapter"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(epub_path), book)
    return epub_path


def save_chapter(page_name, chapter_name, title, paragraphs):
    txt_path = save_txt(txt_dir_for(page_name), chapter_name, title, paragraphs)
    epub_path = save_epub(epub_dir_for(page_name), chapter_name, title, paragraphs)
    print(f"Saved:\n  {txt_path}\n  {epub_path}")


# ---------------------------------------------------------------------------
# Core chapter fetch+save routine
# ---------------------------------------------------------------------------

def process_chapter(page_name, chapter_name, confirm=True):
    """
    Fetch, display a short preview, optionally confirm, then save.
    Returns the BeautifulSoup of the fetched page (for nav links),
    or None if the user declined to save.
    """
    url = build_url(page_name, chapter_name)
    print(f"\nFetching: {url}")
    try:
        soup = fetch_soup(url)
        title = extract_title(soup, fallback=chapter_name)
        paragraphs = extract_paragraphs(soup)
    except (requests.RequestException, ValueError) as exc:
        print(f"Error: {exc}")
        return None

    preview = paragraphs[0][:150]
    print(f'Loaded "{title}" ({len(paragraphs)} paragraphs). Preview: {preview}...')

    if confirm:
        answer = input("Save this chapter? [Y/n]: ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("Skipped.")
            return soup

    save_chapter(page_name, chapter_name, title, paragraphs)
    return soup


# ---------------------------------------------------------------------------
# Interactive post-save menu
# ---------------------------------------------------------------------------

def interactive_loop(page_name, chapter_name, soup):
    current_url = build_url(page_name, chapter_name)

    while True:
        print("\nWhat next?")
        print("  [n] Next chapter")
        print("  [p] Previous chapter")
        print("  [c] Enter a different chapter-name")
        print("  [q] Quit")
        choice = input("> ").strip().lower()

        if choice == "q":
            print("Goodbye.")
            return

        if choice == "c":
            chapter_name = input("Chapter name: ").strip()
            if not chapter_name:
                print("Chapter name cannot be empty.")
                continue
            new_soup = process_chapter(page_name, chapter_name, confirm=True)
            if new_soup is not None:
                soup = new_soup
                current_url = build_url(page_name, chapter_name)
            continue

        if choice in ("n", "p"):
            anchor_id = "next_chap" if choice == "n" else "prev_chap"
            nav_url = find_nav_url(soup, current_url, anchor_id)
            if nav_url is None:
                label = "next" if choice == "n" else "previous"
                print(f"No {label} chapter link found on this page.")
                continue

            new_page_name, new_chapter_name = parse_page_and_chapter_from_url(nav_url)
            if new_chapter_name is None:
                print("Could not parse the navigation link's URL. Skipping.")
                continue

            print(f"Navigating to: {nav_url}")
            new_soup = process_chapter(new_page_name, new_chapter_name, confirm=True)
            if new_soup is not None:
                soup = new_soup
                page_name, chapter_name = new_page_name, new_chapter_name
                current_url = nav_url
            continue

        print("Unrecognized choice.")


# ---------------------------------------------------------------------------
# --save-till batch mode
# ---------------------------------------------------------------------------

def save_till(page_name, start_chapter_name, do_till):
    chapter_name = start_chapter_name
    current_url = build_url(page_name, chapter_name)

    for step in range(1, do_till + 1):
        print(f"\n[{step}/{do_till}]")
        url = build_url(page_name, chapter_name)
        try:
            soup = fetch_soup(url)
            title = extract_title(soup, fallback=chapter_name)
            paragraphs = extract_paragraphs(soup)
        except (requests.RequestException, ValueError) as exc:
            print(f"Error fetching {url}: {exc}")
            print("Stopping batch run.")
            return

        save_chapter(page_name, chapter_name, title, paragraphs)
        current_url = url

        if step == do_till:
            break

        nav_url = find_nav_url(soup, current_url, "next_chap")
        if nav_url is None:
            print("No next-chapter link found. Stopping batch run early.")
            return

        new_page_name, new_chapter_name = parse_page_and_chapter_from_url(nav_url)
        if new_chapter_name is None:
            print("Could not parse next-chapter URL. Stopping batch run.")
            return

        page_name, chapter_name = new_page_name, new_chapter_name

    print("\nBatch run complete.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Extract chapter text/epub from the configured site."
    )
    parser.add_argument(
        "positional",
        nargs="*",
        metavar="ARG",
        help="page-name chapter-name (both required together, or omit both)",
    )
    parser.add_argument(
        "--clear-default-page",
        action="store_true",
        help="Clear the saved default page-name.",
    )
    parser.add_argument(
        "--save-till",
        nargs=2,
        metavar=("CHAPTER_NAME", "DO_TILL"),
        help="Start at CHAPTER_NAME and follow 'next chapter' DO_TILL times, "
        "saving each chapter without confirmation. Uses the saved "
        "default page-name.",
    )
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.clear_default_page:
        clear_default_page_name()
        return

    if args.save_till:
        start_chapter_name, do_till_raw = args.save_till
        try:
            do_till = int(do_till_raw)
            if do_till < 1:
                raise ValueError
        except ValueError:
            print("Error: <do-till> must be a positive integer.")
            sys.exit(1)

        page_name = get_default_page_name()
        if not page_name:
            print(
                "No default page-name is set yet. Run the app normally once "
                "(providing page-name and chapter-name) before using "
                "--save-till."
            )
            sys.exit(1)

        save_till(page_name, start_chapter_name, do_till)
        return

    if len(args.positional) == 1:
        print(
            "Error: provide both page-name and chapter-name together, "
            "or neither. Got only one argument."
        )
        sys.exit(1)

    if len(args.positional) > 2:
        print("Error: too many arguments. Expected: <page-name> <chapter-name>.")
        sys.exit(1)

    if len(args.positional) == 2:
        page_name, chapter_name = args.positional
        set_default_page_name(page_name)
    else:
        page_name = get_default_page_name()
        if not page_name:
            page_name = input("Page name: ").strip()
            if not page_name:
                print("Error: page-name cannot be empty.")
                sys.exit(1)
            set_default_page_name(page_name)
        else:
            print(f"Using saved page-name: {page_name}")

        chapter_name = input("Chapter name: ").strip()
        if not chapter_name:
            print("Error: chapter-name cannot be empty.")
            sys.exit(1)

    soup = process_chapter(page_name, chapter_name, confirm=False)
    if soup is None:
        sys.exit(1)

    interactive_loop(page_name, chapter_name, soup)


if __name__ == "__main__":
    main()
