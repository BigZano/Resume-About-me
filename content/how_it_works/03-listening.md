<!-- page-date: 2026-11-25 -->

# Listening

The Listening block in the Now sidebar shows the ten tracks I played most over the last seven days. A static site can't ask Spotify anything, and putting a Spotify token in the browser of a site whose source is public is a non-starter. So a GitHub Action does the asking, writes the answer to a file, and the site gets built from that file.

## The one file in the middle

`content/listening.json` is the only thing connecting the two halves. The script that talks to Spotify, [scripts/fetch_listening.py](https://github.com/BigZano/Resume-About-me/blob/main/scripts/fetch_listening.py), never sees any HTML. The code that makes the HTML, [src/Gen_Content/render_listening.py](https://github.com/BigZano/Resume-About-me/blob/main/src/Gen_Content/render_listening.py), never sees Spotify or the network.

Because the file is committed, a fresh clone builds with real tracks and no secrets. If it's missing or garbage, the block says "Nothing logged yet" and the build carries on, because a clone must always build. Names go through `html.escape()` since band names love an ampersand. And the file only holds what gets shown: artist, title and a play count. The repo is public and the block is text only.

## Why it polls

I first planned on Spotify's top tracks endpoint, a rolling four-week ranking. It's stable, but it barely moves and it isn't really "this week". The endpoint that knows what I actually played is recently-played, and it only returns the last 50 plays. That's a few hours of listening, not a week.

So the Action ([listening.yml](https://github.com/BigZano/Resume-About-me/blob/main/.github/workflows/listening.yml)) wakes up every four hours, at 17 minutes past because GitHub delays runs that land on the hour, and folds those 50 plays into a rolling seven-day log. The log lives in the GitHub Actions cache and is never committed, since it has timestamps in it and the repo is public. Caches can't be edited once saved, so each run saves a new one under a fresh name and restores the newest by prefix. Plays are deduplicated, so overlapping polls don't count a song twice, and anything older than seven days falls off the end. If the cache gets evicted, the log starts over and refills.

That's why the first week after a fresh start keeps showing the old chart. Spotify only hands back the last 50 plays and won't let me look back any further, so a brand new log can't know what I listened to before it began. It writes down when it started, and until it's seven days old the publish step leaves the committed chart alone instead of swapping in a thin one.

About once a day a run also publishes. It decides by checking whether `listening.json` was last committed 20 or more hours ago, not by the clock, because scheduled runs can show up hours late. Publishing means counting plays per track and taking the top ten. Ties go to the most recently played track, then to artist and title, so the order can't flap around and cause a commit every day:

```python
    # sorted()/sort() are stable, so sort by the weakest key first.
    ranked = sorted(counts.items())                       # artist, title
    ranked.sort(key=lambda kv: kv[1][1], reverse=True)    # most recent
    ranked.sort(key=lambda kv: kv[1][0], reverse=True)    # most plays
```

## Never make it worse

A bad day can't overwrite good data. A response I can't read stops the run instead of quietly becoming an empty list. A week with no plays leaves the old chart alone. If the chart didn't change, nothing is written, so nothing is committed. That makes `fetched_at` mean "when the chart last changed", not "when the job last ran", which is more useful anyway.

## The two clocks

Spotify refresh tokens die six months after I authorize, and refreshing doesn't extend that. It's the one failure the setup can't fix itself. So [scripts/check_token_age.py](https://github.com/BigZano/Resume-About-me/blob/main/scripts/check_token_age.py) does plain date math on a variable holding the day I authorized, with no network. At 30 days out the workflow opens a GitHub issue labeled `spotify-token`, which lands in my email without any mail setup. At zero it opens the issue and fails the run. If Spotify ever hands back a new refresh token, the script prints it loudly, because a workflow can't rewrite its own secret.

The other clock is sneakier. Public repos get their scheduled workflows switched off after 60 days of no activity, which would take the reminder down too. So if the newest commit is 45 or more days old, the next publish run writes a fresh timestamp anyway, just to reset the counter.

I did think about embedding a Spotify player, which would have deleted all of this. It would also have added a few hundred KB of someone else's JavaScript to a site that hosts its own fonts, with a bright green widget on a page the color of embers. I'll take the Action.
