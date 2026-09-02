/* ============================================================
   Landing-page guestbook cell — the newest mark, on the front door.

   The landing page is the front door and this card is the only live
   dependency on it, so it degrades through three layers and never
   shows a broken box:

     1. fetch OK    -> render the newest mark, write the cache
     2. fetch fails -> render the last known good mark from localStorage
     3. no cache    -> the card goes cold

   Layer 3 is not a state this file builds. It is the markup that was
   already in titlepage.html: the standing invitation and a working
   "Sign it" link. Going cold only adds a class, so a visitor with no
   JS at all and a visitor whose network died land on the same card.

   Two rules are load-bearing:

   XSS. The Worker stores and returns text exactly as typed; it is not
   an HTML renderer. This file is, and it is the only thing standing
   between a visitor's <script> and the page. Every piece of entry text
   goes through textContent on a node built here. No HTML-parsing sink
   appears in this file at all — src/tests/test_gb_cell.py fails the
   build if one does.

   Moderation. The cache holds message_display and never message_raw,
   so a hidden entry cannot resurface unswapped, and it carries a 24h
   TTL so a moderated entry self-evicts. An authoritative empty answer
   from the Worker clears the cache outright.
   ============================================================ */
(function () {
  "use strict";

  var API = "https://api.bretzanotelli.work";
  var CACHE_KEY = "gb_cache";
  var TTL_MS = 24 * 60 * 60 * 1000;
  var KEEP = 2;                 /* the current mark and one previous */
  var TIMEOUT_MS = 8000;

  var card = document.getElementById("gb-latest");
  if (!card) {
    return;
  }
  var slot = card.querySelector(".gb-sig");
  if (!slot) {
    return;
  }

  /* ── the cache ────────────────────────────────────────── */
  /* Private browsing throws on the mere act of touching localStorage,
     and a quota-full origin throws on write. Neither may take out the
     card, so both directions swallow and carry on. */

  function readCache() {
    try {
      var raw = window.localStorage.getItem(CACHE_KEY);
      if (!raw) {
        return [];
      }
      var parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return [];
      }
      var now = Date.now();
      var fresh = [];
      for (var i = 0; i < parsed.length; i += 1) {
        var entry = parsed[i];
        if (
          entry &&
          typeof entry.cachedAt === "number" &&
          now - entry.cachedAt >= 0 &&
          now - entry.cachedAt < TTL_MS
        ) {
          fresh.push(entry);
        }
      }
      return fresh;
    } catch (err) {
      return [];
    }
  }

  /* Fields are copied one at a time on purpose. Whitelisting what goes
     in is what guarantees message_raw can never reach the cache; a
     spread of the response plus a delete would not. */
  function cacheable(entry) {
    return {
      name: text(entry.name),
      message_display: text(entry.message_display),
      created_at: text(entry.created_at),
      cachedAt: Date.now()
    };
  }

  function writeCache(entry) {
    try {
      var next = [cacheable(entry)];
      var kept = readCache();
      for (var i = 0; i < kept.length && next.length < KEEP; i += 1) {
        if (kept[i].created_at !== next[0].created_at) {
          next.push(cacheable(kept[i]));
        }
      }
      window.localStorage.setItem(CACHE_KEY, JSON.stringify(next));
    } catch (err) {
      /* Nothing downstream depends on the write succeeding. */
    }
  }

  function clearCache() {
    try {
      window.localStorage.removeItem(CACHE_KEY);
    } catch (err) {
      /* As above. */
    }
  }

  /* ── rendering ────────────────────────────────────────── */

  function text(value) {
    return String(value == null ? "" : value);
  }

  function stamp(iso) {
    var when = new Date(iso);
    if (isNaN(when.getTime())) {
      return "";
    }
    return when.toISOString().slice(0, 10);
  }

  function line(tag, className, value) {
    var node = document.createElement(tag);
    node.className = className;
    node.textContent = value;
    return node;
  }

  function render(entry, state) {
    var parts = [
      line("span", "gb-who", text(entry.name)),
      line("span", "gb-said", text(entry.message_display))
    ];

    var iso = text(entry.created_at);
    var shown = stamp(iso);
    if (shown) {
      var when = line("time", "gb-when", shown);
      when.setAttribute("datetime", iso);
      parts.push(when);
    }

    /* One swap, so the invitation is never on screen beside a mark and
       no half-built state is ever visible. */
    slot.replaceChildren.apply(slot, parts);
    card.classList.remove("is-cold");
    card.classList.add(state);
  }

  /* Layer 3. The static markup already says the right thing, so going
     cold adds a class and touches nothing else — no spinner to strand,
     no error copy on the front door. */
  function cool() {
    card.classList.remove("is-live", "is-cached");
    card.classList.add("is-cold");
  }

  function fallback() {
    var cached = readCache();
    if (cached.length > 0) {
      render(cached[0], "is-cached");
    } else {
      cool();
    }
  }

  /* ── the request ──────────────────────────────────────── */

  function signal() {
    if (typeof AbortSignal !== "undefined" && AbortSignal.timeout) {
      return AbortSignal.timeout(TIMEOUT_MS);
    }
    return undefined;
  }

  fetch(API + "/entries?limit=1", {
    method: "GET",
    headers: { accept: "application/json" },
    signal: signal()
  })
    .then(function (response) {
      if (!response.ok) {
        throw new Error("bad status");
      }
      return response.json();
    })
    .then(function (data) {
      var entries = data && Array.isArray(data.entries) ? data.entries : null;
      if (entries === null) {
        throw new Error("unreadable payload");
      }
      /* An empty answer is authoritative, not an outage: either nobody
         has signed yet or the newest mark was just moderated away. In
         both cases the cache is wrong and the card is honestly cold. */
      if (entries.length === 0) {
        clearCache();
        cool();
        return;
      }
      render(entries[0], "is-live");
      writeCache(entries[0]);
    })
    .catch(fallback);
})();
