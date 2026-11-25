<!-- page-date: 2026-11-25 -->

# The guestbook

GitHub Pages hands out files. It can't accept a POST, so it can't take a guestbook entry. A guestbook needs somewhere to send the entry, somewhere to keep it, and a way to read it back so you see your own signature appear. That made it the first server-side anything this site has had.

I went with a small Cloudflare Worker plus a D1 database (SQLite underneath) at `api.bretzanotelli.work`. Cloudflare already sits in front of the domain, and there's no server of mine to patch. I wrote the Worker in Python because I can audit Python and can't yet audit JavaScript. I skipped hosting it at home behind a tunnel, because every power blip would become site downtime and it would point a public write path at the network my file server lives on.

## The build stays offline

The build never talks to the Worker. [generate_guestbook_page.py](https://github.com/BigZano/Resume-About-me/blob/main/src/Gen_Content/generate_guestbook_page.py) only fills in a template, and the entries load in your browser through [static/guestbook.js](https://github.com/BigZano/Resume-About-me/blob/main/static/guestbook.js). Same rule as Listening: no network, no secrets. That script is also the only thing that turns entries into HTML, and it only uses `textContent`, so someone typing a script tag gets a weird-looking message instead of an exploit. A test fails if an HTML-parsing call ever shows up in it.

## Moderation, without printing the bad words

The rules live in four small pure modules in [worker/src](https://github.com/BigZano/Resume-About-me/tree/main/worker/src) and the Worker file is a thin shell around them, so every decision can be tested offline.

- **Normalize first.** Text is folded to a plain form (accents and invisible characters gone, lowercase, lookalike letters from other alphabets turned back into Latin ones), then read several ways: leetspeak undone, repeated letters squashed, spacing and punctuation stripped. Order matters: an early draft swapped lookalikes before lowercasing, which let capital ones through.
- **The list is hashes.** The repo is public, so blocked terms are stored as SHA-256 digests instead of words, which keeps a wall of slurs out of a repo with my name on it. The plain list lives outside the repo, and the tests use harmless fake ones.
- **Scunthorpe.** Anything that searches inside words flags innocent ones. A short allowlist is cut out of the text before the checks run, so Scunthorpe and a handful of real surnames sign in fine. Names are only checked for slurs, links and length, so joke names get in. Slurs are the line.
- **Hidden, not deleted.** A blocked message is saved with a hidden flag, so I can audit the filter's mistakes. Ordinary swearing is allowed: it's saved as typed and swapped for a sillier word on display (damn becomes dang), with a "show original" button. The server does the swap, so it can't fail open if the page's JavaScript breaks.
- **The rest.** A honeypot field for bots, and a rate limit counted with a salted hash of the IP, so I never hold the address.

The filter is a floor, not the whole policy. It can't tell a cruel joke that uses no slur from a kind one, so I hide those by hand.

## When the scripts fail

The homepage card with the newest signature is the only live dependency on the front door, so it fails in layers. [guestbook-cell.js](https://github.com/BigZano/Resume-About-me/blob/main/static/guestbook-cell.js) fetches the newest entry. If that fails, it shows the last one the browser remembers (display text only, never the original, and gone after 24 hours). If there's nothing remembered, or the script never runs, you get the card that was already in the HTML: an invitation and a link to sign. An empty answer from the Worker counts as an answer, so it clears the cache, or a hidden entry would linger for anyone who'd seen it.

## The bonfire

The name gets the fire, so the guestbook gets a bonfire. Two fires on one page would compete. It's a sword stuck in the ashes with bones and skulls piled around it, always lit, because a bonfire that goes out looks like a broken page. It grows as the wall fills up, and signing makes it bloom and say one line at random:

```js
  var FLOURISHES = [
    "Humanity Restored",
    "Ember Restored",
    "Great Rune Restored"
  ];
```

With reduced motion on, the fire stays lit but stops moving. A rejected message gets a pop-up of Fry from Futurama mooning some executives. [Bret: what's your Dark Souls bonfire story, and why did it end up on the guestbook?]
