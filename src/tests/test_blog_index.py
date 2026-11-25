import contextlib
import io
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from Gen_Content.generate_blog_index import (
    DEFAULT_GENRE,
    _extract_genre,
    generate_blog_index,
)

TEMPLATE = "<html><body><main>{{ BlogPosts }}{{ PaginationNav }}</main></body></html>"


def _post(title: str, genre_comment: str = "") -> str:
    """Markdown for one post, with an optional raw genre comment line."""
    return f"{genre_comment}\n# {title}\n\nSome body text for {title}.\n"


def _render(posts: dict[str, str], posts_per_page: int = 10) -> str:
    """Render the first blog index page from {filename: markdown}.

    Everything happens inside a throwaway directory. generate_blog_index
    writes a page-date comment back into any markdown file that lacks one,
    so the real content/ tree must never be pointed at from a test.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        blog_dir = root / "content" / "dev_diary"
        blog_dir.mkdir(parents=True)
        for name, markdown in posts.items():
            (blog_dir / name).write_text(markdown, encoding="utf-8")

        template_path = root / "template.html"
        template_path.write_text(TEMPLATE, encoding="utf-8")
        dest_path = root / "out" / "dev_diary.html"

        with contextlib.redirect_stdout(io.StringIO()):
            generate_blog_index(
                str(root / "content"),
                str(template_path),
                str(dest_path),
                posts_per_page=posts_per_page,
            )
        return dest_path.read_text(encoding="utf-8")


class _PreviewParser(HTMLParser):
    """Collects what the filter JS and CSS rely on from each preview."""

    def __init__(self):
        super().__init__()
        self.articles: list[dict] = []
        self.tags_seen: list[str] = []
        self._in_article = False
        self._in_meta = False
        self._in_genre_tag = False

    def handle_starttag(self, tag, attrs):
        self.tags_seen.append(tag)
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()

        if tag == "article" and "blog-post-preview" in classes:
            self._in_article = True
            self.articles.append({
                "data_genre": attrs.get("data-genre"),
                "meta_children": [],
                "genre_tag_text": None,
                "time_outside_meta": False,
            })
        elif not self._in_article:
            return
        elif tag == "div" and "post-meta" in classes:
            self._in_meta = True
        elif tag == "time" and not self._in_meta:
            self.articles[-1]["time_outside_meta"] = True
        elif self._in_meta and tag in ("time", "span"):
            self.articles[-1]["meta_children"].append((tag, tuple(classes)))
            if tag == "span" and "genre-tag" in classes:
                self._in_genre_tag = True
                self.articles[-1]["genre_tag_text"] = ""

    def handle_endtag(self, tag):
        if tag == "article":
            self._in_article = False
        elif tag == "div":
            self._in_meta = False
        elif tag == "span":
            self._in_genre_tag = False

    def handle_data(self, data):
        if self._in_genre_tag:
            self.articles[-1]["genre_tag_text"] += data


def _parse(page_html: str) -> _PreviewParser:
    parser = _PreviewParser()
    parser.feed(page_html)
    return parser


class TestExtractGenre(unittest.TestCase):
    def test_absent_tag_defaults_to_dev_diary(self):
        self.assertEqual(_extract_genre("# Title\n\nJust prose.\n"), "dev-diary")

    def test_default_constant_is_dev_diary(self):
        self.assertEqual(DEFAULT_GENRE, "dev-diary")

    def test_empty_markdown_defaults(self):
        self.assertEqual(_extract_genre(""), "dev-diary")

    def test_normal_tag(self):
        md = "<!-- genre: game-review -->\n# Title\n"
        self.assertEqual(_extract_genre(md), "game-review")

    def test_tag_may_appear_after_other_comments_and_content(self):
        md = "<!-- page-date: 2026-01-01 -->\n# Title\n\nBody\n\n<!-- genre: tutorial -->\n"
        self.assertEqual(_extract_genre(md), "tutorial")

    def test_other_comments_alone_do_not_count(self):
        md = "<!-- page-date: 2026-01-01 -->\n# Title\n"
        self.assertEqual(_extract_genre(md), "dev-diary")

    def test_messy_whitespace_and_case(self):
        md = "<!--    genre:    Game Review   -->\n"
        self.assertEqual(_extract_genre(md), "game-review")

    def test_tight_comment_without_spaces(self):
        self.assertEqual(_extract_genre("<!--genre:Retro-Games-->"), "retro-games")

    def test_underscores_and_runs_of_spaces_become_single_hyphens(self):
        self.assertEqual(
            _extract_genre("<!-- genre: GAME___Review \t  Notes -->"),
            "game-review-notes",
        )

    def test_stray_and_repeated_hyphens_are_tidied(self):
        self.assertEqual(_extract_genre("<!-- genre: --game--review-- -->"), "game-review")

    def test_digits_survive(self):
        self.assertEqual(_extract_genre("<!-- genre: Top 10 -->"), "top-10")

    def test_injection_attempt_yields_safe_slug(self):
        slug = _extract_genre('<!-- genre: "><script> -->\n# Title\n')
        self.assertEqual(slug, "script")
        for ch in '<>"\'&/= ':
            self.assertNotIn(ch, slug)

    def test_attribute_breakout_attempt_yields_safe_slug(self):
        slug = _extract_genre('<!-- genre: x" onmouseover="alert(1) -->')
        self.assertRegex(slug, r"^[a-z0-9-]+$")

    def test_value_with_nothing_usable_falls_back(self):
        for junk in ('!!!', '"><', '---', '___', "  "):
            with self.subTest(junk=junk):
                self.assertEqual(
                    _extract_genre(f"<!-- genre: {junk} -->"), "dev-diary"
                )

    def test_empty_value_falls_back(self):
        self.assertEqual(_extract_genre("<!-- genre: -->"), "dev-diary")

    def test_non_ascii_is_dropped_not_kept(self):
        self.assertEqual(_extract_genre("<!-- genre: café notes -->"), "caf-notes")

    def test_first_tag_wins(self):
        md = "<!-- genre: first -->\n<!-- genre: second -->\n"
        self.assertEqual(_extract_genre(md), "first")


class TestBlogIndexRendering(unittest.TestCase):
    def test_article_carries_data_genre(self):
        page = _render({"2026-01-01-a.md": _post("Alpha", "<!-- genre: game-review -->")})
        articles = _parse(page).articles
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["data_genre"], "game-review")
        self.assertIn('<article class="blog-post-preview" data-genre="game-review">', page)

    def test_post_without_tag_renders_dev_diary(self):
        page = _render({"2026-01-01-a.md": _post("Alpha")})
        articles = _parse(page).articles
        self.assertEqual(articles[0]["data_genre"], "dev-diary")
        self.assertEqual(articles[0]["genre_tag_text"], "Dev Diary")

    def test_genre_tag_span_exists_with_title_cased_label(self):
        page = _render({"2026-01-01-a.md": _post("Alpha", "<!-- genre: game-review -->")})
        self.assertIn('<span class="genre-tag">Game Review</span>', page)
        self.assertEqual(_parse(page).articles[0]["genre_tag_text"], "Game Review")

    def test_messy_tag_gives_clean_slug_and_label(self):
        page = _render({"2026-01-01-a.md": _post("Alpha", "<!--  genre:  GAME_review  -->")})
        article = _parse(page).articles[0]
        self.assertEqual(article["data_genre"], "game-review")
        self.assertEqual(article["genre_tag_text"], "Game Review")

    def test_time_and_genre_tag_are_wrapped_in_post_meta(self):
        page = _render({"2026-01-01-a.md": _post("Alpha", "<!-- genre: tutorial -->")})
        article = _parse(page).articles[0]
        self.assertFalse(article["time_outside_meta"])
        self.assertEqual(
            article["meta_children"],
            [("time", ()), ("span", ("genre-tag",))],
        )

    def test_every_post_gets_its_own_genre(self):
        page = _render({
            "2026-03-01-c.md": _post("Gamma", "<!-- genre: game-review -->"),
            "2026-02-01-b.md": _post("Beta"),
            "2026-01-01-a.md": _post("Alpha", "<!-- genre: tutorial -->"),
        })
        articles = _parse(page).articles
        # sorted newest first by filename
        self.assertEqual(
            [a["data_genre"] for a in articles],
            ["game-review", "dev-diary", "tutorial"],
        )
        self.assertEqual(
            [a["genre_tag_text"] for a in articles],
            ["Game Review", "Dev Diary", "Tutorial"],
        )

    def test_injection_attempt_cannot_break_out_of_markup(self):
        page = _render({
            "2026-01-01-a.md": _post("Alpha", '<!-- genre: "><script>alert(1)</script> -->'),
        })
        parsed = _parse(page)
        self.assertNotIn("script", parsed.tags_seen)
        self.assertNotIn("<script", page)
        article = parsed.articles[0]
        self.assertRegex(article["data_genre"], r"^[a-z0-9-]+$")
        self.assertRegex(article["genre_tag_text"], r"^[A-Za-z0-9 ]+$")

    def test_genre_survives_page_date_writeback_on_temp_copy(self):
        # generate_blog_index rewrites markdown that lacks a page-date. The
        # genre comment must still be there afterwards, and only the temp
        # copy may change.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blog_dir = root / "content" / "dev_diary"
            blog_dir.mkdir(parents=True)
            md_path = blog_dir / "2026-01-01-a.md"
            md_path.write_text(_post("Alpha", "<!-- genre: tutorial -->"), encoding="utf-8")
            template_path = root / "template.html"
            template_path.write_text(TEMPLATE, encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                generate_blog_index(
                    str(root / "content"),
                    str(template_path),
                    str(root / "out" / "dev_diary.html"),
                )

            rewritten = md_path.read_text(encoding="utf-8")
            self.assertIn("<!-- page-date: 2026-01-01 -->", rewritten)
            self.assertEqual(_extract_genre(rewritten), "tutorial")


if __name__ == "__main__":
    unittest.main()
