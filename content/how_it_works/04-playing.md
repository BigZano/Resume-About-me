<!-- page-date: 2026-11-25 -->

# Playing

The Playing block in the Now sidebar is the Listening trick again, pointed at Steam. A script asks Steam what I've been playing, writes `content/playing.json`, and the build reads that file. That was the point of building Listening the way I did: a new source is one script, one JSON file and one small renderer, and the rest of the site never hears about it.

## What's different

Steam is a lot easier to deal with than Spotify.

- **No play log.** Spotify only remembers the last 50 plays, so I had to collect them myself. Steam already hands back the last two weeks of playtime per game, so one fetch is the whole job. It only runs on the once-a-day publish run, not every four hours.
- **No expiring token.** It needs an API key and my Steam ID, both stored as repository secrets. No OAuth dance, no six-month clock, no reminder issue. The key rides in the query string because that's how Steam wants it, and the script never prints it.
- **Hours, not plays.** Steam reports minutes. [scripts/fetch_playing.py](https://github.com/BigZano/Resume-About-me/blob/main/scripts/fetch_playing.py) keeps the top five games and converts to hours with one decimal.

That conversion is a tiny function with a lesson in it:

```python
def _minutes_to_tenths_of_an_hour(minutes):
    """Whole minutes -> tenths of an hour, rounding half up.

    Integer arithmetic on purpose: round(minutes / 60, 1) works on a float,
    so 9 minutes (exactly 0.15 h) comes out as 0.1 or 0.2 depending on how
    the binary fraction happens to fall. Here 9 minutes is always 0.2 h.
    """
    return int((minutes + 3) // 6)
```

## What's the same

The script knows nothing about HTML. The file holds only game names and hours, with no app IDs and no lifetime playtime, because the repo is public. If my profile's game details are private, Steam answers with an empty response, and the script fails loudly instead of writing that over a good file. If nothing changed, nothing is written.

In the workflow, the Steam step is allowed to fail without stopping the Spotify chart, but the last step turns the run red so I still notice. If the two secrets aren't set yet, the script says so and exits cleanly. Until there's a playing.json, the block shows a line I wrote by hand in the template, the way the Reading block works.

## League of Legends

Planned, not here yet. Riot's API wants a key, and the development keys expire every 24 hours, which is no use for a job that runs while I'm asleep. I need a personal key, and I'm waiting on one. When it shows up it's the same shape again: another script, another JSON file. The row will show my most-played champions, my overall win rate, and time played, so it sits right alongside the Steam games.
