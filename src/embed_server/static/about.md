<!doctype html>
<html lang="en">
<head>
<title>About</title
><style>
tr,td,th {border-bottom: 1px solid #ccc;}
tr:nth-child(even) {
  background-color: rgba(150, 212, 212, 0.4);
}
th:nth-child(even),td:nth-child(even) {
  background-color: rgba(150, 212, 212, 0.4);
}
</style>
</head>
<body>

# embed.nio-bot.dev
embed.nio-bot.dev is a simple embed server for Matrix bots.

- [Source code (GitHub)](https://github.com/nexy7574/embed.nio-bot.dev)
- [Documentation](/docs)

## Background
There isn't really a similar feature to discord's rich embeds in Matrix. As such, bots made with 
[nio-bot](https://pypi.org/project/nio-bot) can't send fancy looking embeds. The closest we can get is with HTML,
which is very limited in the clients it is even supported in.

embed.nio-bot.dev takes advantage of link previews, which are supported in a lot of clients, to send embeds.
By using the [OpenGraph](https://ogp.me) protocol, we are able to render embeds that look vaguely similar to
discord's rich embeds, allowing for bots to send much more distinct messages.

## Why OpenGraph?
We were originally going to develop this to use [oEmbed](https://oembed.com), but it would require additional
configuration on homeservers - OpenGraph, as limited as it is, does not.

## Usage
Take a look at [the documentation](/docs) for more information on how to use embed.nio-bot.dev.

### Rate-limits
In order to prevent abuse and to keep the service running smoothly, embed.nio-bot.dev has a generous rate-limit.

Rate-limits are per IP address, and are sorted into the following buckets:

<table>
    <thead>
        <tr>
            <th>Bucket Name</th>
            <th>Bucket Limit (hits/timeframe)</th>
            <th>Description</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>`global`</td>
            <td>60/30s</td>
            <td>All endpoints</td>
        </tr>
        <tr>
            <td>`generate`</td>
            <td>30/60s</td>
            <td>Any endpoint that generates an embed (e.g. `GET /embed/quick`, `GET /embed/:code`)</td>
        </tr>
        <tr>
            <td>`create`</td>
            <td>10/60s</td>
            <td>Any endpoint that creates a new embed (e.g. `POST /embed/create`)</td>
        </tr>
        <tr>
            <td>`edit`</td>
            <td>10/60s</td>
            <td>Any endpoint that edits an embed (e.g. `PUT /embed/:code`)</td>
        </tr>
        <tr>
            <td>`delete`</td>
            <td>15/60s</td>
            <td>Any endpoint that deletes an embed (e.g. `DELETE /embed/:code`)</td>
        </tr>
    </tbody>
</table>
</body>
</html>

