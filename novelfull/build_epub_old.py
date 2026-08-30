#!/usr/bin/env python3
"""
Build a single .epub from a directory of chapter .txt files.

Usage:
    python build_epub.py <directory-name>

Expects files inside <directory-name> named like:
    chapter-<chapter-number>-<chapter-name-with-dashes>.txt

For each file:
    - The first two lines are dropped (these are the title + blank line
      written by the scraper, and are not wanted in the epub body).
    - The chapter number is used for ordering (and shown in the ToC).
    - The dash-separated chapter-name is turned into a readable title,
      e.g. "this-is-a-test-chapter-name" -> "This is a test chapter name".

You'll be prompted for the book's title (used as the epub's title and
as the output filename: <book-name>.epub, saved inside <directory-name>).
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


FILENAME_PATTERN = re.compile(r"^chapter-(\d+)-(.+)\.txt$", re.IGNORECASE)


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


def discover_chapters(directory: Path):
    """
    Return a list of dicts: {number, raw_name, title, path},
    sorted by chapter number ascending.
    """
    chapters = []
    for txt_path in directory.glob("*.txt"):
        match = FILENAME_PATTERN.match(txt_path.name)
        if not match:
            print(f"Skipping (name doesn't match pattern): {txt_path.name}")
            continue
        number_str, raw_name = match.groups()
        chapters.append(
            {
                "number": int(number_str),
                "raw_name": raw_name,
                "title": format_chapter_title(raw_name),
                "path": txt_path,
            }
        )

    if not chapters:
        return chapters

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

    output_path = directory / f"{sanitize_filename(book_name)}.epub"
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
