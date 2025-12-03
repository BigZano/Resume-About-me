<!-- page-date: 2025-12-02 -->


# Advent of Code: Day 2 in the bag!

<a href="../dev_diary.html" class="back-button">← Back to Blog</a>

Day two of Advent of Code, day two of a regex coming in handy. I didn't set out to accidentally commit to using a regex per day? But hey here we are. We'll see if we can hit 3/3 after the next challenge drops at 12 UTC. Same as yesterday, we're going to look at my code below and make fun of it a bit. This is after solving part 2, so I had to remove the regex matches from part 1, so ignore the unused imports 😢. I am but a humble, terrible programmer. 


```python
import itertools
import re

list_of_ranges = [
    (5542145, 5582046),
    (243, 401),
    (884211, 917063),
    (1174, 1665),
    (767028, 791710),
    (308275, 370459),
    (285243789, 285316649),
    (3303028, 3361832),
    (793080, 871112),
    (82187, 123398),
    (7788, 14096),
    (21, 34),
    (33187450, 33443224),
    (2750031, 2956556),
    (19974, 42168),
    (37655953, 37738891),
    (1759, 2640),
    (55544, 75026),
    (9938140738, 9938223673),
    (965895186, 966026269),
    (502675, 625082),
    (11041548, 11204207),
    (1, 20),
    (3679, 7591),
    (8642243, 8776142),
    (40, 88),
    (2872703083, 2872760877),
    (532, 998),
    (211488, 230593),
    (3088932, 3236371),
    (442734, 459620),
    (8484829519, 8484873271),
    (5859767462, 5859911897),
    (9987328, 10008767),
    (656641, 673714),
    (262248430, 262271846),
]

def repeating_pattern(s):
    n = len(s)
    for L in range(1, n // 2 + 1):
        if n % L == 0:
            sub = s[:L]
            if sub * (n // L) == s:
                return True
    return False



total_invalid_sum = 0

for start, end in list_of_ranges:
    for id_num in range(start, end + 1):
            s = str(id_num)
            if repeating_pattern(s):
                  total_invalid_sum += id_num




print(total_invalid_sum)
```

This one was a bit more straightforward (no 4k line input file to deal with lol). The main challenge here was identifying numbers that were repeating in sequence. This here is the solution after solving part 2, but thats really just small tweaks to the for loop. The "magic" (if your magicial happens to be inebreated) is in the repeating patterns function. I've been working on incorporating more smaller helpers like this, just to kind of clean things up and keep them readable. Overall I'm actually pretty happy with this one, it runs (we're going to ignore the fact that it's O(n^2) in the worst case here), and it was another really fun exercise. I'm not aiming for elegance here, I'm just happy I'm getting the answers correct. 


Now, for the darker portion: 

I've finally submitted to social media. I've set up small scrips to post out to X, Mastodon and Bluesky when I publish a new article. I'm not one for much of social media, (if you want to chat, open an issue on Github or email me. Discord if you know me lol), but I do want to share my work with others. Like my TUI for 365 administration - that's a neat tool that could help others along with other projects I have that could be useful. So, setup a small python script that uses the respective APIs to post out a link. Once I create the sites, I'll be able to link the creds and push them out automagically. 