# Menlo Coach on your own site

The table app can run on a server and be opened from any device at an address
such as `https://menlo.bet/coach/`. It is the same program with the same
answers; what differs is listed at the end.

## What it needs

- A server you control with Python 3.10 or newer (`python3 --version`) and a
  web server in front on the same machine. The files here are for Caddy and
  systemd.
- **A login in front of it.** The coach has none. It keeps one table per
  mode, for one user, so whoever can open the address can see and change
  your tables.

## Steps (as root on the server)

1. The program:

   ```bash
   git clone --depth 1 -b claude/gifted-thompson-ohocok https://github.com/sduhne/CS_frontend /opt/menlo-coach
   cd /opt/menlo-coach && python3 -m unittest tests.test_app_server tests.test_app_package    # about 15 seconds
   ```

2. The service: copy `deploy/menlo-coach.service` to
   `/etc/systemd/system/`, set `--public-url` to the address people will
   type (and the port, if 8765 is taken), then

   ```bash
   systemctl daemon-reload && systemctl enable --now menlo-coach
   systemctl status menlo-coach --no-pager | head -5
   curl -s -H "Host: menlo.bet" http://127.0.0.1:8765/api/ping      # {"app": "menlo-coach", ...}
   ```

3. The web server: put the lines of `deploy/Caddyfile.snippet` inside the
   site's block, choose the login (the site's own, or a password of its
   own), then `caddy validate --config /etc/caddy/Caddyfile` and
   `systemctl reload caddy`. Validate first: a mistake here stops the whole
   site from reloading.

4. Check from outside: `https://menlo.bet/coach/` asks for the login, shows
   the first-run form, and after Start, `N`, two cards, the coach answers.
   Without the login it must answer 401 or send you to the login page:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://menlo.bet/coach/api/view     # 401 (or 302), never 200
   ```

To update: `cd /opt/menlo-coach && git pull && systemctl restart menlo-coach`.
To remove: `systemctl disable --now menlo-coach`, take the lines out of the
Caddyfile, reload Caddy. The tables stay in `/var/lib/menlo-coach` until
that folder is deleted.

## How it is built for this

- The page asks the program at addresses beside itself (`api/view`, not
  `/api/view`), so it works under any path. The web server must send
  `/coach` to `/coach/` and strip the prefix (`handle_path` does).
- `--public-url` names the address people type. The program then also
  answers requests that arrive under that name, and takes changes only from
  pages of that address: a page of another site cannot change the table. It
  still listens on 127.0.0.1 only, and with this option it never moves to
  another port.
- `tests.test_app_server.BehindAWebServer` checks those rules. A browser run
  behind a small stand-in web server (first-run form, a hand, the coach's
  answer, a reload, the refusals) was done on Linux; nothing has been run
  behind Caddy itself.

## What is the same, and what is not

| | On your computer | On the site |
|---|---|---|
| The answers, the modes, the keys | the same program | the same program |
| Where the tables are kept | your computer | the server: open the address on a phone and the table is there |
| Speed of an answer | a tenth to half a second | the server's processor decides; add the time of one request for every key |
| Who can use it | whoever is at the computer | whoever has the login; one table per mode, shared |
| Two devices at once | (one page) | both see the same table; a change made on a stale page is refused and the page reloads |
| Starting it | the .bat file or the .exe | always on; nothing to start |

The tables on your computer do not move by themselves: copy
`tournament/app/*.json` into `/var/lib/menlo-coach/` (and restart the
service) to take them along.

It is for study and play money, like the program on the computer: the
notice on the page says so and stays.


## The quick guide: a folder of files

The quick guide is not a program. `guide/` holds a page and its tables;
the web server hands them out as they are, and the page keeps the user's
choices in their own browser. Nothing is stored on the server, so it needs
no login of its own (put it behind one if the address should stay private).

1. The files are in the same checkout: `/opt/menlo-coach/guide/`
   (`index.html`, `guide.css`, `guide.js`, `fonts.css`, `fonts/`, `data.js`).
   Without the coach, copy that one folder anywhere the web server can read.
2. Put the second block of `deploy/Caddyfile.snippet` inside the site's
   block, then `caddy validate --config /etc/caddy/Caddyfile` and
   `systemctl reload caddy`.
3. Check: `https://menlo.bet/guide/` shows the page, and

   ```bash
   curl -s -o /dev/null -w "%{http_code} %{size_download}\n" https://menlo.bet/guide/data.js    # 200 and the size of the file
   ```

To update: `git pull` in the checkout (or copy the folder again). The tables
are one file of a few megabytes; with `encode` the web server sends it
compressed.

Not run behind Caddy or on the server: the page was checked from the disk
and behind a small stand-in web server, in a browser on Linux.
