<!-- page-date: 2025-11-11 -->
<!-- landing-blurb: Diablo II, the Navy, Linux, and the Salamanders. -->
# About Me

<a href="index.html" class="back-button">← Back</a>

Games are why I got into computers, and they're why I stuck around. The first time I saw the flames move on the Diablo II title screen, I was *hooked*.

Three moments stand out. First, a friend and I ran VPN sessions over Hamachi to play Diablo II together, because we were too stupid to realize Battle.net did that exact thing. Second, in high school parts were scarce, so I got creative, and it ended with me "frankensteining" two computers together to play Diablo 3 on release. It "worked" in the sense that it ran the game...but shortly after worked no longer. It was an expensive lesson in making sure everything is supported with each other, parts wise. Third, I made a couple hundred dollars flipping things on the Diablo 3 auction house.

## The Navy

I served in the Navy as an aviation ordnanceman. It had nothing to do with computers, but the travel shaped me anyway. It exposed me to cultures, ways of thinking and living, and experiences I never would have had otherwise.

## Learning the hard way

My homelab started as two virtual machines on a painfully slow computer, where I spent a lot of time building and breaking my own network for practice. Then the pandemic hit, so there was *considerably* more time to practice, and I started poking at Python and Rust.

My first IT job felt like "drinking from a firehose", and I just wasn't ready. So I stepped back and taught myself, and that was the year I moved to Linux full time. Between WINE, drivers and audio software, the hiccups were many and the road was long, but it made the command line second nature and changed how I think about technical problems. I'm mostly on Windows now, with Linux over SSH, but that stuck.

The learning never stopped. These days it mostly happens through [projects](workshop.html).

## The Legion

I run a Warhammer 40K community, the XVIIIth Legiones Astartes, the Salamanders. We're 2,000+ people, and I've helped build it since Space Marine 2 came out. Communication and patience is the name of the game, and I could not be prouder of how far we've come.

Armory Bot grew out of that community. It started life as Req_bot, a small helper for event days and heavy-traffic days, and it's been a fun "game" to play with the members. Today it sits in <span data-stat="armory-servers">35 servers</span> with <span data-stat="armory-members">70,000+</span> members between them. The clan site, [sm2salamanders.site](https://sm2salamanders.site), came out of the same community.

## What keeps me busy now

I love learning new technologies. What I keep coming back to is automation: making things build, test and deploy themselves, and making things "talk" to each other (the networking side is my favorite). A few examples:

- This site's [scheduled GitHub Action](https://github.com/BigZano/Resume-About-me/blob/main/.github/workflows/listening.yml) keeps the Spotify chart and the Steam games on my homepage fresh, and I [wrote up how it works](how_it_works/03-listening.html).
- [salamanders-site](https://github.com/BigZano/salamanders-site/tree/main/.github/workflows) deploys to GitHub Pages with checks, and runs tests on every pull request.
- [Better Windows Calendar](https://github.com/BigZano/Better-Windows-Calendar/blob/master/.github/workflows/release.yml) turns a tagged version into a built Windows installer.
- [Pysteroids](https://github.com/BigZano/Pysteroids/tree/main/.github/workflows) builds the game for Windows, Linux and macOS when I tag a version, and pushes the builds straight to itch.io.

A lot of my day-to-day building is SysAdmin and IT-admin tooling, all kept in Git. [admin-toolkit](https://github.com/BigZano/admin-toolkit) is a Go terminal UI that runs my PowerShell admin scripts, and a pile of PowerShell sits behind it in private repos.

This site started as a boot.dev project that got out of hand, and I'm working on a Bachelor's at WGU.

<a href="index.html" class="back-button">← Back</a>
