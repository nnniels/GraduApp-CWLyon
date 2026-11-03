I haven't opened the repo or the tagged JSON file, since you said they're unrelated. The advice below is generic and assumes the app is built from scratch.



## 1. How hard is it to get text or files back?



Text is trivial. Photos are moderate. Both are small tasks at 12 users.



| Option | Complexity | Pros | Cons |
|---|---|---|---|
| **HTML form POST to your server** | Low | No JavaScript needed, works everywhere | Page reloads, no progress feedback |
| **`fetch()` + `FormData` to an upload endpoint** | Low-medium | Smooth UX, with a preview and a "sent ✓" message | A bit of JS, and you must handle errors on a flaky mobile connection |
| **Third-party form or storage (Google Forms, Firebase, Supabase)** | Low | No backend to run | Account setup, privacy, and less control over the flow |
| **Telegram or WhatsApp group instead of in-app upload** | Zero | No code, and people already know how to use it | Not integrated with the challenge flow, and it gets messy to verify |



**Photo caveats:**

- Phone photos are 3–12 MB. Resize them client-side (canvas) or cap the upload size, because mobile data in the field is unreliable.
- Use `<input type="file" accept="image/*" capture="environment">` to open the camera directly.
- iPhones produce HEIC files. Safari usually converts them to JPEG for `accept="image/*"`, but test it.
- Validate the file type and size on the server, and store files under generated names rather than the user-supplied name.

**My recommendation:** use `fetch` + `FormData` to your own endpoint and save to disk. At this scale, a folder of images plus a JSON or SQLite file is enough.

## 2. Hosting for under 24 hours with about 12 people



| Option | Effort | Pros | Cons |
|---|---|---|---|
| **Laptop + tunnel (Cloudflare Tunnel, ngrok, Tailscale Funnel)** | Low | Free, gives you HTTPS, no router config, and you can see the uploads directly | The laptop is a single point of failure (sleep, Wi-Fi, battery, VPN). Corporate laptops may block tunnels, which matters for a Volvo laptop. |
| **Laptop + port forwarding** | Medium | No third party | Needs a public IP and router access, has no HTTPS, and exposes your home network. I'd avoid it. |
| **Free PaaS (Render, Fly.io, Railway, PythonAnywhere)** | Low-medium | Laptop-independent, public URL with HTTPS, and you can deploy from git | Free tiers sleep or have ephemeral disks, so uploads can vanish. Download the data or use external storage. |
| **Small VPS (about €5 for one month, Hetzner/DigitalOcean)** | Medium | Stable, full control, persistent disk | You do the Linux and HTTPS setup (Caddy makes this easy), and it costs a little. |
| **Static front end (Netlify/GitHub Pages) + Supabase/Firebase backend** | Medium | Very robust and no server to maintain | You have to learn two systems |

**HTTPS is not optional.** Geolocation and the camera APIs only work over HTTPS in mobile browsers, and a tunnel or a PaaS provides it automatically.


**My recommendation:** use a PaaS or a cheap VPS, because you can't be the single point of failure while you're in the field. A tunnel from the laptop is acceptable if you test it end to end beforehand. Also use a work laptop with care, since a company device is not an ideal host for a public service.


## 3. Hardware sensitivity



- **The server side isn't sensitive.** 12 users is negligible, and a Raspberry Pi would do.

- **The laptop is where things go wrong:**

&#x20; - Disable sleep, hibernate and lock-triggered network drops.
&#x20; - Stay plugged in.
&#x20; - Check that Wi-Fi doesn't change networks or that VPN doesn't kick in.
&#x20; - Watch for Windows updates restarting it overnight.

- **The client side is the real variable.** Phones differ in browser, GPS accuracy, camera behaviour and battery. Test on both iOS Safari and Android Chrome.



## 4. Code structure



I'd go with a small Python app (Flask or FastAPI) or Node (Express). You said you know a few languages, so pick the one you know best. Frameworks like Next.js are overkill here.



```

treasure-hunt/

├── app.py                 # routes: /, /api/challenges, /api/submit
├── config.py              # secrets, paths, upload limits (from env vars)
├── challenges.json        # content: id, title, text, lat/lng, unlock rule, answer hash
├── storage.py             # save submissions (SQLite or JSON) and files
├── static/
│   ├── index.html         # map + challenge panel
│   ├── app.js             # Leaflet map, fetch calls, geolocation
│   └── style.css
├── uploads/               # photos (gitignored)
├── data.db                # SQLite (gitignored)
└── README.md              # how to run and deploy

```



**Key design choices:**

- **Map:** Leaflet with OpenStreetMap tiles. It's free and needs no API key. Google Maps requires a billing account
- **Challenge content:** keep it in data (JSON), not in code, so you can edit it without redeploying
- **Identity:** give each team or person a unique link or code (`/t/abc123`) rather than building accounts and passwords. That is much simpler
- **Unlocking:** decide whether challenges unlock on proximity (GPS), on a correct answer, or on a time schedule. Time or answer-based is much more robust than GPS-based
- **Database:** SQLite or even a JSON file. Postgres is overkill.



## 5. Loopholes and cautions



**Spoilers and cheating**

- Anything in the front-end JavaScript is visible to players. If `challenges.json` is served whole, they can read every answer and location in dev tools. Serve only the current challenge from the server, and check answers on the server (compare hashes, never ship the plain answers).
- If the unlock is based on GPS coordinates sent by the browser, they can be spoofed. Accept that or rely on answers, since this is a friendly game.
- Predictable URLs like `/challenge/3` let people skip ahead. Check progress on the server.



**Security**

- Uploads: validate the type, size and count, never execute or serve them as HTML, and rename the files.
- Don't expose an admin or "all submissions" route without a password.
- Keep secrets out of git.
- Rate-limit submissions lightly. A tunnel or public URL can be scanned by bots.



**Privacy**

- Photos can contain EXIF data, including GPS location. Tell participants, and delete everything after the event. Consider whether any minors or non-participants appear in photos.


**Practical, field-related issues**

- Spotty mobile connectivity: show clear errors and offer a retry. Consider saving drafts in `localStorage`.
- GPS needs the permission prompt, which people deny, and indoor accuracy is poor. Always give a manual fallback such as "enter the code at the location".
- Battery drain from continuous GPS and a screen kept on.
- Timezones and clocks: use server time for any scheduling.
- Have a plan B, such as a printed paper version or a Telegram group, in case the app dies.
- Run a full dry run with 2–3 friends on their own phones, outdoors, beforehand. This is the single most valuable thing you can do.



## Suggested path



1. Build the minimal version: Flask/FastAPI + Leaflet + JSON challenges + form upload.
2. Deploy on a PaaS or a €5 VPS. Use a tunnel from the laptop only as a fallback.
3. Add per-team links, server-side answer checks and the upload limits.
4. Do the dry run.
5. After the event, export the submissions and delete the data.



I can go deeper on any part, such as the upload endpoint, the answer-hashing scheme, or the tunnel setup. If you tell me your preferred language, I can make the structure concrete.

