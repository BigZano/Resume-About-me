<!-- page-date: 2025-12-1 -->
<!-- page-date: 2025-12-02 -->

<a href="../dev_diary.html" class="back-button">← Back to Blog</a>

# Advent of Code is here!

Figured I've almost been programming a year now, it'd be a fun experiment and I've not been disappointed. 

I'm going to aim to do an entry after each day's challenge, and today involved a fun exercise with looping over a dataset to rotate a "lock" to find the passcode. I'm running as a part of the BootDev leaderboard, and in the Discord group it's a blast to see the different strategies folks have used to solve day one. I opted for a more...caveman solution than most, turning the entire thing into a string (4k lines btw) and iterating over that. 

```Python
    import re
    tokens = re.findall(r'([RL])\s*(\d+)', list_of_turns_raw)
    list_of_turns = [int(n) if d == 'R' else -int(n) for d, n in tokens]

    dial_position = 50
    zero_count = 0

    def hit_on_zero(p: int, amt: int) -> int:
        # count landings on 0s while moving and stopping
        a = abs(amt)
        if a == 0:
            return 0
        if amt > 0:
            i0 = (100 - p) % 100
        else:
            i0 = p % 100
        if i0 == 0:
            return 1 + (a - 1) // 100
        elif a <= i0:
            return 0
        else:
            return 1 + (a - i0 - 1) // 100

    for turn in list_of_turns:
        zero_count += hit_on_zero(dial_position, turn)
        dial_position = (dial_position + turn) % 100

    return zero_count

if __name__ == "__main__":
    result = unlock_door(None)
    print(f"Final zero count: {result}")
```

This got me the answer, (I know, shock horror), but I was only iterating over a string and I still think the time complexity is O(n), which while not being the best could definitely have been worse. 

Outside of the AoC challenge, I've been extending the functionality of the AI agent that BootDev lead us through creating. Ultimately I am recreating something similar to Claude, but with the ability to help me study for IT tasks as well as code. I've been building the analyzer functions for the past few days, and it it's coming along pretty wel. It can write files, read them back, analyze the structure of the code base, and suggest low tier improvements. I moved from the Gemini API to the llama 3.1:8b-Instant model, which while not as powerful as Gemini possibly, it's still very capable and most importantly to me, *local and open source*. I can bundle it with my agent, and I don't have to worry about API limits or costs. I'm totally onboard with waiting for it to reason through tasks (I told it to slow down and take it's time purposely in config), and it's been a fun experience so far. Next few steps are going to be adding web search with a ephemeral Docker container and SearXNG, and using DuckDuckGo's API for queries as a backup if it can't answer itself. Along with web search, I'm going to be adding system search, since I want it to act as a digital assistant as well. So I'm looking at either RIPgrep or Recoll, depending on how I want to handle search and indexing. 

Overall, the job hunt continues and I'm able to keep pouring time into learning new things. Lets see where this takes us, and we'll be back after the next Advent of Code challenge!

<a href="../dev_diary.html" class="back-button">← Back to Blog</a>