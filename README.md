# CoDraw: A Collaborative Whiteboard

Distributed Systems project, WS26, Group 21.

Several people draw on one shared canvas from different computers. Strokes,
the eraser and "Clear board" show up on every connected screen, and the board
is saved to disk so it survives a server restart.

**Current version:** one server, any number of browsers. Replication across
several servers, leader election (Bully algorithm) and fault tolerance are
planned next (see [Roadmap](#roadmap)).

## Files

| File | What it does |
|------|--------------|
| `server.py` | The WebSocket server. Accepts browser connections, gives every drawing operation the next sequence number, saves it, and broadcasts it to all connected browsers. Sends the full history to a browser when it connects or reconnects. |
| `log_store.py` | Saves operations to `board.jsonl` (one JSON line per operation) and loads them again on startup. Ignores an operation whose ID it has already seen, so retries never draw twice. |
| `index.html` | The browser client. Draws on a canvas, sends each finished stroke to the server, and redraws the board from the confirmed operations. Has colour, brush size, eraser and clear. Reconnects automatically. |
| `requirements.txt` | Python packages to install (`websockets`). |
| `.gitignore` | Keeps the board log and local files out of Git. |
| `board.jsonl` | Created by the server when you first draw. Do not commit it. |

## Requirements

- **Python 3.11.** This is what we developed with. Other recent Python 3
  versions should work but we have not tested them.
- **websockets** (`pip install websockets`), version 12 or newer.
- A modern browser (Chrome, Edge, Firefox).
- For use on several computers: all laptops on the **same network**
  (same Wi-Fi or LAN).

## Setup

```bash
git clone this repo
cd <repo-folder>

# optional but recommended: a virtual environment
python -m venv venv
# Windows:      venv\Scripts\activate
# macOS/Linux:  source venv/bin/activate

pip install -r requirements.txt
```

## Running it

### On one laptop (quick test)

1. Start the server:
   ```bash
   python server.py
   ```
   You should see `Server listening on ws://0.0.0.0:8765`.
2. Open `index.html` in two browser tabs and draw in one of them.

### On two laptops

Pick one laptop to **run the server** (call it Laptop A). Only Laptop A runs
`server.py`.

1. **Find Laptop A's IP address**
   - Windows: `ipconfig`, then look for *IPv4 Address*
   - macOS: `ipconfig getifaddr en0`
   - Linux: `hostname -I`
2. **Start the server on Laptop A:** `python server.py`
3. **Allow the connection through Laptop A's firewall.** On Windows, click
   *Allow access* when the Python firewall prompt appears, or allow inbound
   TCP port `8765`.
4. **On Laptop A,** open `index.html`. It connects to `localhost` and needs no
   changes.
5. **On Laptop B,** open `index.html` in an editor and set the server address
   near the top of the `<script>` section to Laptop A's IP:
   ```js
   const SERVER_HOST = "192.168.1.10";   // Laptop A's IP address
   ```
   Then open `index.html` in the browser.

   Instead of editing the file you can open it with the address in the URL:
   `index.html?server=192.168.1.10`

The header should show **Connected** and **Users: 2**. Draw on one laptop and
the stroke should appear on the other.

> The IP address always belongs to the laptop running `server.py`, not to the
> laptop you are opening the page on. Do not commit your personal IP address
> change if your teammates use different ones.

## Using the whiteboard

- **Draw:** hold the mouse button (or touch) and drag.
- **Colour and brush size:** controls in the header.
- **Eraser:** toggle *Eraser* on and draw over what you want to remove.
- **Clear board:** removes everything for all users.
- **Status bar:** connection state, number of users, last committed operation
  number, and operations still waiting for confirmation (*Pending*).

## How it works

1. A browser sends a finished stroke as an operation with a unique `op_id`.
2. The server gives it the next sequence number (`seq`), appends it to
   `board.jsonl`, and broadcasts it as a `COMMIT` to every browser.
3. Browsers draw the board by replaying committed operations in `seq` order,
   starting after the last `CLEAR`.
4. If a browser loses its connection, it reconnects, receives the full history
   and re-sends anything unconfirmed with the same `op_id`. The server ignores
   duplicates.

To start with an empty board, stop the server and delete `board.jsonl`.

## Troubleshooting

| Problem | Likely cause and fix |
|---------|----------------------|
| Header says *Disconnected, retrying* | The server is not running, or the IP in `SERVER_HOST` is wrong. |
| Works on Laptop A but not on Laptop B | Firewall on Laptop A is blocking port 8765, or the laptops are on different networks. |
| `ModuleNotFoundError: websockets` | Run `pip install -r requirements.txt` (inside the virtual environment if you use one). |
| `Address already in use` | Another server is running on port 8765. Stop it, or start with `python server.py --port 8766` and change `SERVER_PORT` in `index.html`. |
| Cannot draw | The client only accepts drawing while connected. Wait for *Connected*. |



## Team

Yashodhan Moghe, Mayuresh Shendkar, Shruti Kudale, Mrunal Murudkar
