#!/usr/bin/env python3
"""
Build a single .epub from a directory of chapter .txt files.

Usage:
    python build_epub.py <directory-name>

<directory-name> is expected to be the chapter-txt folder produced by
webscraper.py, e.g. <page-name>/allchaptersarchivetxt/. The combined
book epub is saved one level up, at <page-name>/<book-name>.epub.

Expects files inside <directory-name> named like:
    <anything>-<chapter-number>-<chapter-name-with-dashes>.txt
    <anything>-<chapter-number>.txt          (name missing -> you'll be prompted)

The word before the number (e.g. "chapter") is ignored entirely, so
typos like "chaoter-3-..." or "chspter-7.txt" are read just fine —
only the number and name matter.

For each file:
    - The first two lines are dropped (these are the title + blank line
      written by the scraper, and are not wanted in the epub body).
    - The chapter number is used for ordering (and shown in the ToC).
    - The dash-separated chapter-name is turned into a readable title,
      e.g. "this-is-a-test-chapter-name" -> "This is a test chapter name".
    - If a file has no name segment, you're prompted to enter one.

You'll be prompted for the book's title (used as the epub's title and
as the output filename: <book-name>.epub).
"""

import argparse
import re
import sys
from pathlib import Path

try:
    from ebooklib import epub
except ImportError:
    print("Missing dependency 'ebooklib'. Install with: pip install ebooklib")
    sys.exit(1)


# Matches: [<any-word>-]<number>[-<name>].txt
# The word before the number (e.g. "chapter", "chaoter", "chspter") is
# ignored entirely — only the number and optional name matter.
GENERIC_PATTERN = re.compile(
    r"^(?:[A-Za-z]+-)?(?P<number>\d+)(?:-(?P<name>.+))?\.txt$", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_chapter_title(raw_name):
    """
    Turn 'this-is-a-test-chapter-name' into
    'This is a test chapter name'.
    """
    words = raw_name.replace("-", " ").strip()
    words = re.sub(r"\s+", " ", words)
    if not words:
        return words
    return words[0].upper() + words[1:]


def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def prompt_for_chapter_name(number: int, filename: str) -> str:
    print(f"\n'{filename}' (chapter {number}) is missing a chapter name.")
    while True:
        name = input(f"Enter a name for chapter {number}: ").strip()
        if name:
            return name
        print("Name cannot be empty.")


def discover_chapters(directory: Path):
    """
    Return a list of dicts: {number, raw_name, title, path},
    sorted by chapter number ascending.

    The prefix word before the number (e.g. "chapter", "chaoter") is
    ignored entirely — only <number> and optional <name> are read, so
    typos in that word don't matter.

    - <word>-<N>-<name>.txt  -> normal case
    - <word>-<N>.txt         -> missing name, prompts for one
    Anything without a parseable number is skipped with a note.
    """
    chapters = []
    unmatched = []

    for txt_path in sorted(directory.glob("*.txt")):
        match = GENERIC_PATTERN.match(txt_path.name)
        if not match:
            unmatched.append(txt_path)
            continue

        number = int(match.group("number"))
        raw_name = match.group("name")

        if raw_name:
            chapters.append(
                {
                    "number": number,
                    "raw_name": raw_name,
                    "title": format_chapter_title(raw_name),
                    "path": txt_path,
                }
            )
        else:
            title = prompt_for_chapter_name(number, txt_path.name)
            chapters.append(
                {"number": number, "raw_name": None, "title": title, "path": txt_path}
            )

    for f in unmatched:
        print(f"Skipping (couldn't find a chapter number in): {f.name}")

    chapters.sort(key=lambda c: c["number"])
    return chapters


def read_chapter_body(path: Path):
    """
    Read the file and drop the first two lines (title + blank line).
    Returns the remaining text, split into paragraphs on blank lines.
    """
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    remaining = lines[2:]
    text = "".join(remaining).strip()

    if not text:
        return []

    # Paragraphs are separated by blank lines.
    raw_paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip().replace("\n", " ") for p in raw_paragraphs if p.strip()]
    return paragraphs


def paragraphs_to_html(paragraphs):
    return "".join(f"<p>{p}</p>" for p in paragraphs)


# ---------------------------------------------------------------------------
# EPUB building
# ---------------------------------------------------------------------------

def build_epub(directory: Path, book_name: str, chapters: list):
    book = epub.EpubBook()
    book.set_identifier(sanitize_filename(book_name) or "book")
    book.set_title(book_name)
    book.set_language("en")

    epub_chapters = []
    toc_links = []

    for chapter in chapters:
        paragraphs = read_chapter_body(chapter["path"])
        if not paragraphs:
            print(f"Warning: no content found in {chapter['path'].name}, skipping.")
            continue

        chapter_heading = f"Chapter {chapter['number']}: {chapter['title']}"
        file_name = f"chap_{chapter['number']:04d}.xhtml"

        epub_chapter = epub.EpubHtml(
            title=chapter_heading, file_name=file_name, lang="en"
        )
        epub_chapter.content = (
            f"<h1>{chapter_heading}</h1>{paragraphs_to_html(paragraphs)}"
        )

        book.add_item(epub_chapter)
        epub_chapters.append(epub_chapter)
        toc_links.append(epub.Link(file_name, chapter_heading, f"chap_{chapter['number']}"))

    if not epub_chapters:
        print("No chapters with usable content were found. Aborting.")
        return None

    book.toc = tuple(toc_links)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + epub_chapters

    output_path = directory.parent / f"{sanitize_filename(book_name)}.epub"
    epub.write_epub(str(output_path), book)
    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build an .epub from a directory of chapter .txt files."
    )
    parser.add_argument("directory", help="Directory containing chapter-*.txt files")
    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"Error: '{directory}' is not a directory.")
        sys.exit(1)

    book_name = input("Book name: ").strip()
    if not book_name:
        print("Error: book name cannot be empty.")
        sys.exit(1)

    chapters = discover_chapters(directory)
    if not chapters:
        print(f"No files matching 'chapter-<number>-<name>.txt' found in {directory}.")
        sys.exit(1)

    print(f"Found {len(chapters)} chapter(s):")
    for c in chapters:
        print(f"  {c['number']:>4}  {c['title']}  ({c['path'].name})")

    output_path = build_epub(directory, book_name, chapters)
    if output_path is None:
        sys.exit(1)

    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
