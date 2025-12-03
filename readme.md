Static site generator project that I'm slowly turning into a portfolio site

## Blog pagination

- Blog archive now paginates in batches of five posts per page.
- Additional index pages are emitted as `dev_diary-page-2.html`, `dev_diary-page-3.html`, etc.

## Social sharing

- Each blog card includes commented share links for X, Mastodon, and Bluesky.
- Define `SITE_BASE_URL` to generate correct absolute URLs when shares are enabled.
- Use `scripts/publish_social.py` to post new articles once provider credentials are configured.
