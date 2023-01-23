# critter-catcher

A simple client to pull videos from my unifi protect cameras so I can keep records of animals who come to visit overnight.

Owes a large debt to a couple projects:

* [pyunifiprotect](https://github.com/AngellusMortis/pyunifiprotect) by @AngellusMortis
* [unifi-protect-backup](https://github.com/ep1cman/unifi-protect-backup) by @ep1cman

In fact, I could have just used [unifi-protect-backup](https://github.com/ep1cman/unifi-protect-backup) for this purpose, but I wanted to write my own thing because I haven't done any asynchronous python before and this is a great chance to dig into that. But if you are looking for a way to back up your unifi protect video you should use unifi-protect-backup.

This initial commit is just a rudimentary script that I used to try out different approaches to handle this with asyncio. It would be much cleaner as a couple of classes. I also need to containerize it and run it as a serivce and all that good stuff, but this is in decent shape for a first commit.
