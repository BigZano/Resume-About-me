/* ============================================================
   Armory Bot's live numbers, on the Workshop and About Me pages.

   Both pages already say the right thing in plain text. This script
   only ever replaces that text with the bot's current figures, so it
   degrades the way guestbook-cell.js does: if it never runs, or the
   request fails, or the answer can't be trusted, the words that were
   in the markup are what a visitor reads. There is no spinner, no error
   copy, and nothing is logged.

   The markup contract:

     <span data-stat="armory-servers">35 servers</span>
     <span data-stat="armory-members">70,000+</span> members between them

   The servers span carries its own word, because "1 server" against
   "36 servers" is this file's call to make. The members span carries
   the bare number, and the sentence around it has to say "members
   between them": the API's `users` is a sum of members across servers,
   so one person in three servers is counted three times. It is not a
   count of people, and no copy near these spans may call it one.

   The validation rules are the ones the bot's own docs site uses for
   the same endpoint (armorybot.win/javascripts/member-total.js):
   `is_ready` must be exactly true, and `guilds` and `users` must both
   be integers of at least 1. Anything else leaves the fallback alone.
   Both numbers are checked before either span is touched, so the page
   never shows a live server count beside a stale member count.

   Two rules are load-bearing:

   No request without a reason. Pages that don't carry the spans make
   no request, which is why this script can sit in the shared page
   template.

   Text only. Every figure goes in through textContent. The numbers
   come from a third-party origin, so nothing here parses markup, and
   src/tests/test_armory_stats.py fails the build if a parsing sink
   appears in this file.
   ============================================================ */
(function () {
  "use strict";

  var STATS_URL = "https://api.armorybot.win/api/stats";
  var TIMEOUT_MS = 5000;

  /* The pure half: the API payload in, the two strings out, or null when
     the numbers can't be trusted. Exported below so node can test it
     without a DOM. */
  function armoryStatsText(stats) {
    if (!stats || typeof stats !== "object" || stats.is_ready !== true) {
      return null;
    }
    var guilds = stats.guilds;
    var users = stats.users;
    if (
      !Number.isInteger(guilds) ||
      !Number.isInteger(users) ||
      guilds < 1 ||
      users < 1
    ) {
      return null;
    }
    return {
      servers:
        guilds.toLocaleString("en-US") + (guilds === 1 ? " server" : " servers"),
      members: users.toLocaleString("en-US")
    };
  }

  function setAll(nodes, value) {
    for (var i = 0; i < nodes.length; i += 1) {
      nodes[i].textContent = value;
    }
  }

  function run() {
    var serverNodes = document.querySelectorAll('[data-stat="armory-servers"]');
    var memberNodes = document.querySelectorAll('[data-stat="armory-members"]');
    if (serverNodes.length === 0 && memberNodes.length === 0) {
      return;
    }
    if (typeof fetch !== "function") {
      return;
    }

    var timer = null;
    function disarm() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    }

    var options = { credentials: "omit" };
    if (typeof AbortController === "function") {
      var controller = new AbortController();
      options.signal = controller.signal;
      timer = setTimeout(function () {
        controller.abort();
      }, TIMEOUT_MS);
    }

    /* The timer stays armed until the body has been read, so a response
       that starts and then stalls is cut off too. */
    fetch(STATS_URL, options)
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (stats) {
        disarm();
        var shown = armoryStatsText(stats);
        if (shown) {
          setAll(serverNodes, shown.servers);
          setAll(memberNodes, shown.members);
        }
      })
      .catch(disarm);
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { armoryStatsText: armoryStatsText };
    return;
  }

  /* Nothing below this line may throw into the page. A missing fetch, a
     blocked request and a DOM that surprises us all end the same way:
     the static text stays. */
  try {
    run();
  } catch (err) {
    /* Nothing downstream depends on this succeeding. */
  }
})();
