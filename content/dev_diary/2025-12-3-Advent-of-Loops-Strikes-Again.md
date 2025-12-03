<!-- page-date: 2025-12-03 -->

# Day 3 of Advent of Code: Lööps Strike Again!

<a href="../dev_diary.html" class="back-button">← Back to Blog</a>

Day three of the Advent is here, and Day 3 is in the bag! Once again, let's take a look at our code and see how we did.

```python
# part 1
total_joltage = 0

for bank in list_of_banks:  # loop for each bank, strip spaces, commas and quotes, confirm digits only
    banks = bank.strip().rstrip(',')
    digits = [int(ch) for ch in banks if ch.isdigit()]

    best = 0  # find best two-digit combination, walk left to right
    max_left = -1
    for d in digits:
        if max_left >= 0:
            candidate = max_left * 10 + d
            if candidate > best:
                best = candidate
        if d > max_left:  # Set max_left to largest digit seen so far
            max_left = d

    total_joltage += best  # add best for this bank to total_joltage

print(total_joltage)
```

## Part 2

```python
total_joltage = 0
k = 12  # digits to turn per bank

for bank in list_of_banks:
    banks = bank.strip().rstrip(',')
    digits = [int(ch) for ch in banks if ch.isdigit()]

    # make stack and pop items for largest k digits
    needed = len(digits) - k
    stack = []
    for d in digits:
        while stack and needed > 0 and stack[-1] < d:
            stack.pop()
            needed -= 1
        stack.append(d)

    selected = stack[:k]  # take first k items from stack
    best = 0
    for d in selected:
        best = best * 10 + d
    total_joltage += best

print(total_joltage)
```

Remembered to snag part one and two this time, and this one was a bit more tough. Finding the right combinations of digits was tough but I eventually got there in the end. Pretty sure it's O(n), which is mid but loads better than yesterday where it was exponential time lol. Got there with a bunch of loops, and was inspired to make the meme below 😁.

![May I have some loops?](../loops.png)

<a href="../dev_diary.html" class="back-button">← Back to Blog</a>
