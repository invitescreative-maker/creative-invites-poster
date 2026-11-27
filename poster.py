"""
poster.py -- runs on GitHub Actions (PC can be off). Same workflow as the Decoded Bharat autopost.

1. Sends a Telegram preview (video + caption + buttons) for every pending job due in the next 24 hours.
2. Reads button taps (only from the owner chat).
     sc:<job>  Approve -> post at the job's post_at
     ap:<job>  Post now
     ch:<job>  Needs changes
     dc:<job>  Discard
3. Posts every approved ("scheduled") job that is due, to @thecreativeinvites via the Graph API.
4. Sends alerts for late, failed or unapproved posts and a broken Instagram token.

Job file jobs/<id>.json: {id, kind: reel|story|carousel, title, caption, video | images, post_at, status}
Secrets (env): IG_ACCESS_TOKEN, IG_USER_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "jobs"
STATE = ROOT / "state.json"
REPO = os.environ.get("GITHUB_REPOSITORY", "invitescreative-maker/creative-invites-poster")

IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
IG_USER = os.environ.get("IG_USER_ID", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OWNER = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GRAPH = "https://graph.facebook.com/v23.0"
TG = f"https://api.telegram.org/bot{TG_TOKEN}"
APPROVAL_BOT = "TheCreativeInvites_bot"
ACCOUNT = "@thecreativeinvites"
IST = timezone(timedelta(hours=5, minutes=30))
MAX_ATTEMPTS = 3


def now():
    return datetime.now(timezone.utc)


def log(m):
    print(f"{now():%Y-%m-%d %H:%M:%S}Z {m}", flush=True)


def nice(iso):
    return datetime.fromisoformat(iso).astimezone(IST).strftime("%a %d %b, %I:%M %p IST")


def tg(method, **kw):
    """Telegram call that never raises and never logs the token."""
    try:
        return requests.post(f"{TG}/{method}", timeout=kw.pop("timeout", 30), **kw).json()
    except Exception as e:
        log(f"telegram {method} failed: {type(e).__name__}")
        return {"ok": False, "description": type(e).__name__}


def say(text, buttons=None):
    body = {"chat_id": OWNER, "text": text[:4000]}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": buttons}
    return tg("sendMessage", json=body)


def load_job(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save_job(job):
    (JOBS / f"{job['id']}.json").write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def raw_url(path):
    return f"https://raw.githubusercontent.com/{REPO}/main/{urllib.parse.quote(path)}"


# ------------------------------------------------------------ previews
def send_preview(job):
    head = f"PREVIEW: {job['title']}\n{job.get('kind', 'reel').upper()} | {nice(job['post_at'])}"
    files = [job["video"]] if job.get("video") else job.get("images", [])
    missing = [f for f in files if not (ROOT / f).exists()]
    if missing or not files:
        say(f"⚠️ {head}\nFile missing in the repo: {', '.join(missing) or 'no media'}")
        return False
    for f in files[:10]:
        path = ROOT / f
        method, field = ("sendVideo", "video") if path.suffix.lower() == ".mp4" else ("sendPhoto", "photo")
        with path.open("rb") as fh:
            r = tg(method, data={"chat_id": OWNER, "caption": head}, files={field: fh}, timeout=300)
        if not r.get("ok"):
            say(f"{head}\n(Could not send the file here: {r.get('description')})\n{raw_url(f)}")
    j = job["id"]
    r = say(f"CAPTION:\n{job.get('caption') or '(none)'}\n\nPosts only if you approve.",
            [[{"text": "✅ Approve", "callback_data": f"sc:{j}"}, {"text": "🚀 Post now", "callback_data": f"ap:{j}"}],
             [{"text": "✏️ Needs changes", "callback_data": f"ch:{j}"}, {"text": "🗑 Discard", "callback_data": f"dc:{j}"}]])
    return bool(r.get("ok"))


def previews_due():
    for p in sorted(JOBS.glob("*.json")):
        try:
            job = load_job(p)
            due = datetime.fromisoformat(job["post_at"])
        except Exception as e:
            log(f"skipping unreadable job file {p.name}: {e}")
            continue
        if job.get("status") == "pending" and not job.get("preview_sent") and due <= now() + timedelta(hours=24):
            if send_preview(job):
                job["preview_sent"] = now().isoformat()
                save_job(job)
                log(f"preview sent for {job['id']}")


# ------------------------------------------------------------ telegram taps
def handle_taps():
    me = tg("getMe").get("result", {}).get("username")
    if me != APPROVAL_BOT:      # never read another bot's inbox
        log(f"TELEGRAM_BOT_TOKEN belongs to @{me}, expected @{APPROVAL_BOT}: taps not read")
        return
    r = tg("getUpdates", json={"timeout": 0})
    updates = r.get("result", [])
    for u in updates:
        cq = u.get("callback_query")
        if not cq:
            continue
        tg("answerCallbackQuery", json={"callback_query_id": cq["id"]}, timeout=15)
        if str(cq["from"]["id"]) != OWNER or str(cq["message"]["chat"]["id"]) != OWNER:
            log("ignored tap from non-owner")
            continue
        action, _, jid = (cq.get("data") or "").partition(":")
        p = JOBS / f"{jid}.json"
        if action not in ("sc", "ap", "ch", "dc") or not jid.isalnum() or not p.exists():
            say("That button belongs to an old or unknown post.")
            continue
        job = load_job(p)
        if job["status"] not in ("pending", "scheduled"):
            say(f"'{job['title']}' is already {job['status']}.")
            continue
        if action == "sc":
            job["status"] = "scheduled"
            say(f"✅ Approved: '{job['title']}' will post to {ACCOUNT} on {nice(job['post_at'])} (PC can be off).")
        elif action == "ap":
            job["status"] = "scheduled"
            job["post_at"] = now().isoformat()
            say(f"✅ Approved: posting '{job['title']}' now.")
        elif action == "ch":
            job["status"] = "needs_changes"
            say("✏️ Marked as needs changes. Tell Claude what to change and a new version will be sent.")
        else:
            job["status"] = "discarded"
            say("🗑 Discarded. Nothing was posted.")
        save_job(job)
    if updates:                  # confirm exactly what was read
        tg("getUpdates", json={"offset": updates[-1]["update_id"] + 1, "timeout": 0})


# ------------------------------------------------------------ instagram
def api(method, path, **params):
    params["access_token"] = IG_TOKEN
    kw = {"params": params} if method == "GET" else {"data": params}
    try:
        r = requests.request(method, f"{GRAPH}/{path}", timeout=120, **kw)
        d = r.json()
    except Exception as e:       # the exception text can contain the URL, so only keep its type
        raise RuntimeError(f"Graph API request failed: {type(e).__name__}")
    if r.status_code >= 400 or "error" in d:
        e = d.get("error", d)
        raise RuntimeError(f"Graph API {r.status_code}: {e.get('message', e)} (code={e.get('code')}, sub={e.get('error_subcode')})")
    return d


def wait_finished(cid, limit=900):
    t0 = time.time()
    while True:
        st = api("GET", cid, fields="status_code,status")
        code = st.get("status_code")
        log(f"container {code}")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {code}: {st.get('status')}")
        if time.time() - t0 > limit:
            raise RuntimeError("timed out waiting for processing")
        time.sleep(10)


def publish(job) -> str:
    kind, caption = job.get("kind", "reel"), job.get("caption", "")
    if kind == "carousel":
        kids = [api("POST", f"{IG_USER}/media", image_url=raw_url(i), is_carousel_item="true")["id"] for i in job["images"]]
        cid = api("POST", f"{IG_USER}/media", media_type="CAROUSEL", children=",".join(kids), caption=caption)["id"]
    elif kind == "story":
        cid = api("POST", f"{IG_USER}/media", media_type="STORIES", video_url=raw_url(job["video"]))["id"]
    else:
        body = {"media_type": "REELS", "video_url": raw_url(job["video"]), "caption": caption, "share_to_feed": "true"}
        if job.get("cover"):
            body["cover_url"] = raw_url(job["cover"])
        cid = api("POST", f"{IG_USER}/media", **body)["id"]
    wait_finished(cid)
    media_id = api("POST", f"{IG_USER}/media_publish", creation_id=cid)["id"]
    try:
        return api("GET", media_id, fields="permalink").get("permalink", media_id)
    except Exception:
        return media_id


def post_due():
    for p in sorted(JOBS.glob("*.json")):
        try:
            job = load_job(p)
            due = datetime.fromisoformat(job["post_at"])
        except Exception as e:
            log(f"skipping unreadable job file {p.name}: {e}")
            continue
        if job.get("status") != "scheduled" or due > now():
            continue
        job["status"] = "posting"
        job["attempts"] = job.get("attempts", 0) + 1
        save_job(job)
        try:
            link = publish(job)
            job.update(status="posted", link=link)
            job.pop("error", None)
            save_job(job)
            say(f"🎉 Posted to {ACCOUNT}: {job['title']}\n{link}")
        except Exception as e:
            job["error"] = str(e)
            if job["attempts"] < MAX_ATTEMPTS:
                job["status"] = "scheduled"
                log(f"attempt {job['attempts']} failed, will retry: {e}")
            else:
                job["status"] = "failed"
                say(f"⚠️ Posting '{job['title']}' failed after {MAX_ATTEMPTS} tries:\n{e}")
            save_job(job)


def watchdog():
    for p in sorted(JOBS.glob("*.json")):
        try:
            job = load_job(p)
            due = datetime.fromisoformat(job["post_at"])
        except Exception:
            continue
        late = (now() - due).total_seconds() / 60
        st = job.get("status")
        msg = None
        if st == "scheduled" and late > 10:
            msg = f"⏰ LATE: '{job['title']}' was due {nice(job['post_at'])}. It posts on the next run. {job.get('error', '')}"
        elif st == "pending" and late > 30:
            msg = f"⏰ '{job['title']}' is NOT approved and its slot has passed. Tap Approve or Discard."
        elif st == "posting" and late > 40:
            msg = f"⚠️ '{job['title']}' is stuck in 'posting'. Check Instagram before retrying."
        if msg and not job.get("late_alerted"):
            say(msg)
            job["late_alerted"] = True
            save_job(job)
    state = load_state()
    if time.time() - state.get("health_at", 0) > 6 * 3600:
        try:
            api("GET", IG_USER, fields="username")
            state["health_ok"] = True
            log("instagram token check ok")
        except Exception as e:
            if state.get("health_ok", True):
                say(f"🚨 Instagram token check FAILED. Posting will stop until fixed:\n{e}")
            state["health_ok"] = False
        state["health_at"] = time.time()
        STATE.write_text(json.dumps(state), encoding="utf-8")


if __name__ == "__main__":
    JOBS.mkdir(exist_ok=True)
    handle_taps()
    previews_due()
    post_due()
    try:
        watchdog()
    except Exception as e:
        log(f"watchdog error: {e}")
    log("done")
