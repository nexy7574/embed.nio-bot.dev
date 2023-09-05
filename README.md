# embed.nio-bot.dev

This is the embed provider running at https://embed.nio-bot.dev, which allows for simple and easy cross-platform
embeds for matrix bots running [nio-bot](https://pypi.org/project/nio-bot).

See: [The documentation](https://embed.nio-bot.dev/docs)

## Why?
The only other way to create messages that stand out as a bot (or just user) is to use the HTML formatting, which is
not supported by all (or many) clients (outside of those that are just electron anyway). However, link previews often
are supported, and this allows for a simple way to create them. The only time this wouldn't work is if the client
has previews disabled or the room is encrypted.

# Running
You should use `docker compose`, which will build the image, and run it with the database and redis servers.
