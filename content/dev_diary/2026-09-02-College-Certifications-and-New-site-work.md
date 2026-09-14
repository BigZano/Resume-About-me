<!-- page-date: 2026-09-02 -->

# College, Certifications, new site features and more

## College again?

Yes, indeed, I am once again a college student. I'm attending WGU to finish out my Bachelors degree in IT. Go figure, the nerd that wants to build a modernized 90s themed site is pursuing an IT degree. So far we've gone through an obtained ITILv4, A+ and Net+, and we're working on Project+ atm. So far it's repeat info from my previous position, but at least now I have the piece of paper that says I know how. I would be lying though, if I didn't say that I'm enjoying fleshing out the more academic side of my work experience.

## New face and features

Yes indeed, the site has also gotten a new face and features! A guestbook directly inspired by guestbooks from the 90s, with some safety rails (try it out, it's fun!), a bit more personal flair like the now listening, working on and reading, picture of my cat, and more. Title letters inspired by DOOM - the flames are actually inspired from a fan remake that I saw, it's as close of an example as I could find code examples for. Next up is remaking the title letters to resemble more DOOM style letters, and add some more fun effects. I also mentioned my cat, so I added a poorly cropped photo of him screaming at me. Lets go into some of the new features, since this is a dev diary after all.

### Guestbook

Alright, nothing here is super groundbreaking, however it's been very fun as both a seasoned IT and a new developer, to get exposure from both sides of the fence. The page itself is just TailwindCSS and HTML5, with VueJS powering what little is needed like the cell and the animations. I chose this stack because I used it on Armory Bot ([shameless self plug btw, it is my site after all](https://armorybot.win)) and it's familiar to me. Where as I worked with Claude more on Armory bot and other web projects, and I did use it on the front end here a bit for the JS still, I made it a point to continue to build the backend infra myself, as I still enjoy the problem solving (even if I don't enjoy the actual code writing aspect of programming).

The backend here is a Python worker, using the Wrangler toolkit from Cloudflare. That's communicating with a Docker container on a local server here which is storing all the messages. In the middle of those two, is my CORS layer as well as all the filtering (feel free to try out the filter. A simple "fuck" won't get you in trouble, but anything heinous will), it contains both a still and a gif for rejected messages. Like I said, nothing really truly groundbreaking, it's all client side with just the one worker communicating with the container, but it was a lot of fun to set up CORS for a different type of database, as well as getting to touch Cloudflare workers for the first time.

### The Now listening block

This one is also, nothing groundbreaking, but it's more fun cause there's more moving parts. I made a Spotify App, created a Python script to create a token for my user (most importantly, to view my recently played). Then, it takes that data as JSON and begins averaging it out based on how many times a song appears that week, then compares it to the calendar month so far, and we post the top 10. This is another feature that is mostly Tailwind and HTML5, with VueJS powering small things here and there. The weekly run is powered by a GH actions run, which was a lot of fun to setup and learn about since my eventual career goal is in either DevOps or CloudOps. Unfortunately, there isn't anything as fun as this available for Audible, so that's a manual update. I know it's possible, since I've seen it, however I'm still looking into how to make a commit tracker on the site that hooks to both GH and Boot.Dev (if possible on that last one.)

### Upcoming

I've got a new plan, and a new idea. More stuff to talk about, I'm going to lean into gaming! I'm going to do game reviews, and a playthrough tracker. I'm going to be playing RDR2 with a friend (after I beat MS2 and the new Onimusha game) so it'll be a fun way to chronicle our journey together through the multiplayer. Gaming is a big part of why I work with computers, and why I want to work in IT in general, so I'd be genuinely crazy if I didn't start putting some of those experiences down.
