/* ============================================================
   Guestbook — read the wall, sign the book.

   XSS boundary: the Worker stores and returns text exactly as it was
   typed. It does not sanitise for HTML, because it is not an HTML
   renderer. This file is the renderer, and it is the only thing
   standing between a visitor's <script> and the page. Every piece of
   entry text therefore goes through textContent on a node this file
   built. No HTML-parsing sink appears in this file, at all, for
   anything — src/tests/test_gb_page.py fails the build if one does.
   ============================================================ */
(function () {
  "use strict";

  var API = "https://api.bretzanotelli.work";
  var LIMIT = 25;
  var TIMEOUT_MS = 10000;

  /* Copy lives here, not in the Worker. The Worker returns stable
     machine codes so the wording can change without a redeploy. */
  var COPY = {
    signed: "Signed. Thanks for stopping by.",
    offline: "Couldn't reach the guestbook. Try again shortly.",
    unreadable: "The guestbook isn't answering right now. Try again shortly.",
    no_marks: "No marks yet. Be the first."
  };

  /* Every documented 400/429 code, and nothing else. An unrecognised
     code falls back to the offline line rather than being trusted. */
  var ERRORS = {
    "empty": "Needs a name and a message.",
    "name_too_long": "Name is over 40 characters.",
    "message_too_long": "Message is over 500 characters.",
    "url_not_allowed": "Links aren't allowed — say it in words.",
    "rate_limited": "Slow down a moment, then try again."
  };

  /* Instant feedback only — the Worker revalidates and its answer is the
     one that counts. Deliberately broad, same as the server-side rule. */
  var LOOKS_LIKE_URL =
    /(https?:\/\/|www\.|\b[a-z0-9-]+\.(com|net|org|io|dev|xyz|ru|co|link|shop|biz|info|top)\b)/i;

  var form = document.getElementById("gb-form");
  var nameInput = document.getElementById("gb-name");
  var messageInput = document.getElementById("gb-message");
  var websiteInput = document.getElementById("gb-website");
  var submit = document.getElementById("gb-submit");
  var counter = document.getElementById("gb-counter");
  var count = document.getElementById("gb-count");
  var status = document.getElementById("gb-status");
  var reject = document.getElementById("gb-reject");
  var list = document.getElementById("gb-entries");
  var empty = document.getElementById("gb-empty");
  var fire = document.getElementById("gb-fire");
  var flourish = document.getElementById("gb-fire-flourish");
  var rejectClose = document.getElementById("gb-reject-close");

  if (!form || !list) {
    return;
  }

  /* ── status line ──────────────────────────────────────── */

  /* The status line is a live region, so it stays in the DOM and keeps
     its reserved height at all times. Toggling `hidden` on a live
     region is what stops screen readers announcing it. */
  function setStatus(text, tone) {
    status.textContent = text;
    status.classList.remove("is-ok", "is-error");
    if (tone) {
      status.classList.add(tone);
    }
  }

  /* Modal where the browser supports it, inline where it does not —
     showModal gives focus trapping, Escape, and the backdrop for free. */
  function showReject() {
    setStatus("");
    if (typeof reject.showModal === "function") {
      if (!reject.open) {
        reject.showModal();
      }
      return;
    }
    /* The open ATTRIBUTE, not the hidden property: a dialog without
       [open] is display:none, so hidden=false would show nothing. */
    reject.setAttribute("open", "");
    reject.focus();
  }

  function hideReject() {
    if (typeof reject.close === "function" && reject.open) {
      reject.close();
      return;
    }
    reject.removeAttribute("open");
  }

  if (rejectClose) {
    rejectClose.addEventListener("click", hideReject);
  }

  /* A click on the backdrop lands on the dialog itself, never on its
     children, so this closes on outside-click without a second overlay
     element to manage. */
  if (reject) {
    reject.addEventListener("click", function (event) {
      if (event.target === reject) {
        hideReject();
      }
    });
  }

  /* ── the fire ─────────────────────────────────────────── */

  /* Heat scales the flame with the number of marks. Always lit — a
     bonfire that goes out reads as a broken page, not an empty guestbook. */
  var HEAT = [
    { at: 15, name: "high" },
    { at: 5, name: "warm" },
    { at: 0, name: "low" }
  ];

  /* What the fire says when a mark lands, one per submission. The three
     games acknowledge the same act in their own words; which one shows
     is luck of the draw. */
  var FLOURISHES = [
    "Humanity Restored",
    "Ember Restored",
    "Great Rune Restored"
  ];

  var bloomTimer = 0;

  function setHeat(marks) {
    if (!fire) {
      return;
    }
    var total = typeof marks === "number" && marks > 0 ? marks : 0;
    for (var i = 0; i < HEAT.length; i += 1) {
      if (total >= HEAT[i].at) {
        fire.dataset.heat = HEAT[i].name;
        return;
      }
    }
  }

  /* One bloom, one line, per accepted mark. Any bloom still running is
     cancelled first, so a second signing restarts cleanly rather than
     stacking a second line on top of the first. */
  function bloom() {
    if (!fire || !flourish) {
      return;
    }
    var line = FLOURISHES[Math.floor(Math.random() * FLOURISHES.length)];

    window.clearTimeout(bloomTimer);
    fire.classList.remove("is-blooming");
    /* force a reflow, or the class re-add is coalesced and the
       animation never restarts */
    void fire.offsetWidth;

    flourish.textContent = line;
    fire.classList.add("is-blooming");

    /* REFACTOR: 3450ms duplicates the 3.4s bloom duration in guestbook.css
       — read it from the animation instead of hardcoding it here too. */
    bloomTimer = window.setTimeout(function () {
      fire.classList.remove("is-blooming");
      flourish.textContent = "";
    }, 3450);
  }

  /* The fire animates continuously, so it should not animate while it
     is off-screen. rootMargin keeps it running just before it scrolls
     back in, so it is never caught mid-freeze. */
  if (fire && typeof window.IntersectionObserver === "function") {
    new window.IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i += 1) {
        fire.classList.toggle("is-idle", !entries[i].isIntersecting);
      }
    }, { rootMargin: "160px" }).observe(fire);
  }

  /* ── entry rendering ──────────────────────────────────── */

  function stamp(iso) {
    var when = new Date(iso);
    if (isNaN(when.getTime())) {
      return "";
    }
    return when.toISOString().slice(0, 10);
  }

  function entryNode(entry) {
    var item = document.createElement("li");
    item.className = "gb-entry";

    var head = document.createElement("div");
    head.className = "gb-entry-head";

    var who = document.createElement("span");
    who.className = "gb-name";
    who.textContent = String(entry.name == null ? "" : entry.name);

    var when = document.createElement("time");
    when.className = "gb-time";
    var iso = String(entry.created_at == null ? "" : entry.created_at);
    var shown = stamp(iso);
    if (shown) {
      when.dateTime = iso;
      when.textContent = shown;
    }

    head.appendChild(who);
    head.appendChild(when);

    var display = String(
      entry.message_display == null ? "" : entry.message_display
    );
    var body = document.createElement("p");
    body.className = "gb-message";
    body.textContent = display;

    item.appendChild(head);
    item.appendChild(body);

    if (entry.has_swap && entry.message_raw != null) {
      var raw = String(entry.message_raw);
      var toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "gb-reveal";
      toggle.textContent = "show original";
      toggle.setAttribute("aria-pressed", "false");
      toggle.addEventListener("click", function () {
        var revealed = toggle.getAttribute("aria-pressed") === "true";
        revealed = !revealed;
        body.textContent = revealed ? raw : display;
        toggle.textContent = revealed ? "hide original" : "show original";
        toggle.setAttribute("aria-pressed", revealed ? "true" : "false");
      });
      item.appendChild(toggle);
    }

    return item;
  }

  function showEmpty(text) {
    empty.textContent = text;
    empty.hidden = false;
  }

  function renderEntries(entries) {
    list.replaceChildren();
    for (var i = 0; i < entries.length; i += 1) {
      list.appendChild(entryNode(entries[i]));
    }
    list.classList.add("is-ready");
    setHeat(entries.length);
    if (entries.length === 0) {
      showEmpty(COPY.no_marks);
    } else {
      empty.hidden = true;
    }
  }

  function signal() {
    if (typeof AbortSignal !== "undefined" && AbortSignal.timeout) {
      return AbortSignal.timeout(TIMEOUT_MS);
    }
    return undefined;
  }

  function loadEntries() {
    fetch(API + "/entries?limit=" + LIMIT, {
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
        var entries = data && Array.isArray(data.entries) ? data.entries : [];
        renderEntries(entries);
      })
      .catch(function () {
        /* Never leave a spinner running. Say what happened. */
        list.replaceChildren();
        list.classList.add("is-ready");
        setHeat(0);
        showEmpty(COPY.unreadable);
      });
  }

  /* ── the counter ──────────────────────────────────────── */

  function updateCount() {
    var used = messageInput.value.length;
    count.textContent = String(used);
    counter.classList.toggle("is-close", used >= 450 && used < 500);
    counter.classList.toggle("is-full", used >= 500);
  }

  /* ── signing ──────────────────────────────────────────── */

  function fail(text) {
    setStatus(text, "is-error");
    status.focus();
  }

  function handleResponse(response, data) {
    var code = data && typeof data.code === "string" ? data.code : "";

    if (response.status === 201 || (response.ok && data && data.ok)) {
      form.reset();
      updateCount();
      setStatus(COPY.signed, "is-ok");
      status.focus();
      if (data && data.entry) {
        list.prepend(entryNode(data.entry));
        list.classList.add("is-ready");
        empty.hidden = true;
        setHeat(list.children.length);
        bloom();
      }
      return;
    }

    if (code === "blocked") {
      showReject();
      return;
    }

    fail(Object.prototype.hasOwnProperty.call(ERRORS, code)
      ? ERRORS[code]
      : COPY.offline);
  }

  function onSubmit(event) {
    event.preventDefault();

    hideReject();
    setStatus("");

    var name = nameInput.value.trim();
    var message = messageInput.value.trim();

    if (name === "" || message === "") {
      fail(ERRORS.empty);
      return;
    }
    if (name.length > 40) {
      fail(ERRORS.name_too_long);
      return;
    }
    if (message.length > 500) {
      fail(ERRORS.message_too_long);
      return;
    }
    if (LOOKS_LIKE_URL.test(name) || LOOKS_LIKE_URL.test(message)) {
      fail(ERRORS.url_not_allowed);
      return;
    }

    submit.disabled = true;

    fetch(API + "/entries", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: name,
        message: message,
        website: websiteInput ? websiteInput.value : ""
      }),
      signal: signal()
    })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            handleResponse(response, data);
          });
      })
      .catch(function () {
        fail(COPY.offline);
      })
      /* A dead network must never leave the form dead with it. */
      .finally(function () {
        submit.disabled = false;
      });
  }

  form.addEventListener("submit", onSubmit);
  messageInput.addEventListener("input", updateCount);

  updateCount();
  setStatus("");
  loadEntries();
})();
