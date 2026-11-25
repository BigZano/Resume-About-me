<!-- page-date: 2026-11-25 -->

# The generator

This site isn't built with a framework. It's built by a pile of Python I wrote, which started as the static site generator project on boot.dev. The first commit is from 2025-09-29 and says "SSG start initial commit lets goooo". For about a month it was a Lord of the Rings blog, then I turned it into this. Everything else on the site sits on top of it.

## Markdown in, HTML out

A page is a markdown file in `content/`. The converter turns it into HTML in three steps, each one a small file in `src/`.

1. `markdown_to_blocks.py` chops the file into blocks on blank lines. Code fences stay in one piece and every heading is a block of its own.
2. `block_to_html.py` looks at how each block starts to decide what it is (heading, quote, list, code, otherwise a paragraph) and builds a tree of nodes.
3. Inside a block, `text_to_textnodes.py` splits the text into plain, bold, italic, code, link and image pieces, and `htmlnode.py` turns each piece into a tag.

The order of that last step matters more than it looks:

```python
def text_to_textnodes(text):
    nodes = [TextNode(text, TextType.PLAIN_TEXT)]
    # Code first, so content like Req_bot is protected from later delimiters.
    nodes = split_nodes_delimiter(nodes, "`", TextType.CODE_TEXT)
    # Images/links before delimiters, so underscores in URLs aren't split.
    nodes = split_nodes_image(nodes)
    nodes = split_nodes_link(nodes)
    nodes = split_nodes_delimiter(nodes, "**", TextType.BOLD_TEXT)
    nodes = split_nodes_delimiter(nodes, "__", TextType.BOLD_TEXT)
    nodes = split_nodes_delimiter(nodes, "*", TextType.ITALIC_TEXT)
    nodes = split_nodes_delimiter(nodes, "_", TextType.ITALIC_TEXT)
    return nodes
```

Code goes first so nothing else touches it, and links come before bold and italics so the underscores in a URL don't turn into italics. I found most of that out the hard way: there's a commit from 2025-10-30 called "fixed about me and delimiter renderings".

The whole converter is roughly 450 lines. `block_types.py` is left over from the boot.dev version, tests and all, and `block_to_html.py` no longer uses it. I should delete it.

It also doesn't escape anything. Text goes into the page exactly as I typed it, so I can drop raw HTML into the markdown when the converter can't do something (the back buttons on the diary posts are hand-written HTML, for one). That's only okay because I'm the only one writing those files. Anything from outside, like Spotify track names, gets escaped first.

## Templates

Pages go through a template in the repo root, with placeholders in double curly braces like `{{ Placeholder }}`. The entire template engine is Python's `str.replace`. The page's own content goes in last, after every other placeholder is filled, so a post can spell out a placeholder name and it stays exactly as typed.

## One build, from scratch

[src/main.py](https://github.com/BigZano/Resume-About-me/blob/main/src/main.py) is the whole build, and it starts by deleting the output folder:

```python
        if os.path.exists(docs_path):
            log_message("Deleting existing docs directory...")
            shutil.rmtree(docs_path)
        os.makedirs(docs_path)
        log_message("Created fresh docs directory")
```

Then it copies `static/` in, renders every markdown file through the template, and builds the dev diary, the homepage and the guestbook page. If one page blows up it logs the error and keeps going, then exits non-zero at the end so a half-built site can't pass for a good one.

Wiping everything means no stale files. The cost is that `docs/` is output, so never edit it by hand, because the next build deletes your edit. GitHub Pages serves that committed folder, so there's no deploy pipeline. One odd habit: if a markdown file has no `page-date` comment, the build writes one into the source file. Building edits your content, which is why every file in `content/` starts with that comment.

## Zero dependencies, on purpose

[pyproject.toml](https://github.com/BigZano/Resume-About-me/blob/main/pyproject.toml) says `dependencies = []`. The build only uses the standard library, so there's nothing to install or update, and the GitHub Action that rebuilds the site has a Python setup step and a build step but no install step. The one optional extra is Pillow, which I used once to shrink a photo from 4.4 MB to 57 KB. Tests are plain `unittest`, and since the old boot.dev-era ones are partly stale, the runner remembers how many already fail and complains if that number grows.

## Why I kept it

Honestly, I never went shopping for anything else. This was a boot.dev project and I just kept building on top of it, one feature at a time, on the same generator. Somewhere along the way it stopped being an exercise and turned into my playground for new ideas, and the place my portfolio and my brand live. That's reason enough to keep it.
