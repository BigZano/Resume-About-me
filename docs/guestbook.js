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

  /* Instant feedback only. The Worker revalidates all of this and its
     answer is the one that counts. Deliberately broad, same as the
     server-side rule: a false positive costs a rephrase, a miss hands
     a link spammer the payload. */
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
  var fireState = document.getElementById("gb-fire-state");

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

  function showReject() {
    setStatus("");
    reject.hidden = false;
    reject.focus();
  }

  function hideReject() {
    reject.hidden = true;
  }

  /* ── the fire ─────────────────────────────────────────── */

  /* Heat is the wall's state, redrawn. Cold is not a styling choice:
     it is what an empty guestbook and an unreachable API both are, and
     the fire must never claim a warmth the wall cannot show. */
  var HEAT = [
    { at: 15, name: "high", label: "Roaring" },
    { at: 5, name: "warm", label: "Burning" },
    { at: 1, name: "low", label: "Embers" },
    { at: 0, name: "cold", label: "Cold" }
  ];

  var stokeTimer = 0;

  function setHeat(marks) {
    if (!fire || !fireState) {
      return;
    }
    var total = typeof marks === "number" && marks > 0 ? marks : 0;
    var step = HEAT[HEAT.length - 1];
    for (var i = 0; i < HEAT.length; i += 1) {
      if (total >= HEAT[i].at) {
        step = HEAT[i];
        break;
      }
    }
    fire.dataset.heat = step.name;
    fireState.textContent = total === 0
      ? step.label
      : step.label + " \u00b7 " + total + (total === 1 ? " mark" : " marks");
  }

  /* One flare when a mark lands. The class is removed on the way out
     so a second signing in the same session flares again. */
  function stoke() {
    if (!fire) {
      return;
    }
    fire.classList.remove("is-stoked");
    /* force a reflow so the animation restarts rather than being
       treated as still-running */
    void fire.offsetWidth;
    fire.classList.add("is-stoked");
    window.clearTimeout(stokeTimer);
    stokeTimer = window.setTimeout(function () {
      fire.classList.remove("is-stoked");
    }, 1200);
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
        stoke();
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
