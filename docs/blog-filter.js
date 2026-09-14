// Genre filter for the blog index. Client-side and per-page only — it
// filters the posts already rendered on the current pagination page, it
// does not reach across pages. Builds itself from whatever data-genre
// values are actually present, so it silently does nothing until posts
// carry more than one genre.
(function () {
  const nav = document.getElementById("genre-filter");
  if (!nav) return;

  const posts = Array.from(document.querySelectorAll(".blog-post-preview[data-genre]"));
  if (posts.length === 0) return;

  const seen = new Set();
  const genres = [];
  for (const post of posts) {
    const slug = post.dataset.genre;
    if (seen.has(slug)) continue;
    seen.add(slug);
    const label = post.querySelector(".genre-tag");
    genres.push({ slug, label: label ? label.textContent.trim() : slug });
  }

  if (genres.length < 2) return;

  function makeButton(slug, label, pressed) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.dataset.genre = slug;
    button.setAttribute("aria-pressed", String(pressed));
    return button;
  }

  const buttons = [makeButton("all", "All", true)];
  for (const { slug, label } of genres) {
    buttons.push(makeButton(slug, label, false));
  }
  buttons.forEach((button) => nav.appendChild(button));

  nav.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-genre]");
    if (!button) return;

    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b === button)));

    const selected = button.dataset.genre;
    for (const post of posts) {
      if (selected === "all" || post.dataset.genre === selected) {
        post.removeAttribute("hidden");
      } else {
        post.setAttribute("hidden", "");
      }
    }
  });

  nav.classList.add("is-active");
})();
