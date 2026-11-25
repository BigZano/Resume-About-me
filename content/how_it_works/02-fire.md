<!-- page-date: 2026-11-25 -->

# The fire

My name at the top of the homepage is on fire. It isn't a video or a GIF. It's a fire simulation on a canvas, in [static/fire.js](https://github.com/BigZano/Resume-About-me/blob/main/static/fire.js), about 300 lines of JavaScript, burning into the letters.

The reason is on my About page: the first time I saw the flames move on the Diablo II title screen, I was hooked on computers. Fire is also the idea the rest of the site hangs on, though not the epic kind. The kind you gather around: a hearth, a forge, a bonfire, a stove. So the name gets to burn.

## The algorithm

It's the fire effect from the PlayStation version of Doom, and it's smaller than it looks. The fire is a grid of numbers, each one how hot that spot is. The bottom row is held near maximum heat, which is the fuel. Then, seventeen times a second, every cell copies its heat into one of the three cells above it (up-left, straight up or up-right, picked at random) and sometimes loses a bit on the way. Heat rises, wanders sideways and cools off, which is most of what a flame does. To draw it, each number is looked up in a palette of 37 colors, from near-black through red and orange to almost white.

Here's the copying step, all of it:

```js
  function spread(src, decay) {
    var rand = (Math.random() * 3) | 0;
    var to = src - rand + 1 - fw;
    if (to < 0 || to >= fire.length) return;
    var v = fire[src] - (rand & 1) * decay;
    fire[to] = v > 0 ? v : 0;
  }
```

`rand` is 0, 1 or 2, and that one roll picks the target: right, straight up, or left. Heat is only lost on the straight-up roll, so one copy in three cools.

## A different height for every column

A plain Doom fire is one flat band of flame. I wanted the flames to vary across the name, like a campfire crossed with the bars on an EQ display, so every column gets its own height limit and cooling rate. Tall columns cool slowly and short ones cool fast.

```js
      var u = (x / fw) * 6.2832;
      var n = Math.sin(u * 2.3 + envPhase) * 0.42
            + Math.sin(u * 5.1 - envPhase * 1.4) * 0.33
            + Math.sin(u * 11.7 + envPhase * 2.2) * 0.25;
      n = n * 0.5 + 0.5;
      var f = (1 - VARIATION) + VARIATION * (0.18 + 0.82 * n);
      capRows[x] = Math.max(2, f * fh);
      decayCol[x] = (2.15 * HOT) / capRows[x];
```

Three sine waves of different sizes are added together to make a lumpy skyline, and every step they slide along at different speeds, so it never quite repeats. One catch: the sideways drift smears the cooling rates out, so cooling alone didn't hold the shape. When the fire gets painted, each column fades out as it nears its limit and anything above it is hidden.

## Into the letters

The fire is painted onto a small hidden canvas and stretched up with smoothing off, so the pixels stay honest. My name is drawn in white on a second hidden canvas, and the fire is only kept where the white is. That gets laid over the visible name, which is charred dark at the bottom and fades to bone color above the flames. A blurred copy goes behind it all for the glow.

The name is in capitals on purpose. Lowercase letters are only about half as tall, so the flames swallowed them whole while only reaching two thirds of the way up the capitals.

## Playing nice with the browser

- It runs 17 steps a second, not once per frame.
- It stops when the canvas scrolls off screen or the tab is hidden, and paints one still frame instead.
- With reduced motion on, it burns for 120 steps up front, paints one lit frame and stays still. It also notices if the setting changes.
- It waits for the display font to load, so the flames burn into the real letters and not a fallback.
- The canvas is labeled with my name, so a screen reader reads a name instead of nothing.

Six numbers at the top of the file control the look, and a comment says to leave them alone. If the script never runs, the name is still there as plain text in the same typeface. The script swaps the text for the fire once it has something to draw. [Bret: the September diary says the flames were inspired by a fan remake you saw. Want to name or link it here?]
