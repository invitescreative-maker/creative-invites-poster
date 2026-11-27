"""Queue a post (same idea as Decoded Bharat's cloud_send.py). Telegram preview is sent by the cloud runner.

  python add_job.py "Title" --video path/to/reel.mp4 --caption-file cap.txt --at "2026-11-27 19:30" [--kind reel|story]
"""
import argparse, json, re, shutil, subprocess, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))


def git(*a):
    subprocess.run(["git", "-C", str(ROOT), *a], check=True)


ap = argparse.ArgumentParser()
ap.add_argument("title")
ap.add_argument("--video", required=True)
ap.add_argument("--caption-file")
ap.add_argument("--at", required=True, help='"YYYY-MM-DD HH:MM" IST')
ap.add_argument("--kind", default="reel", choices=["reel", "story"])
a = ap.parse_args()

src = Path(a.video).resolve()
if not src.exists() or src.stat().st_size > 49 * 1024 * 1024:
    raise SystemExit("video missing, or over 49 MB (Telegram preview limit): compress it first")
when = datetime.strptime(a.at, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
caption = Path(a.caption_file).read_text(encoding="utf-8").strip() if a.caption_file else ""
git("pull", "--rebase", "-q")
name = re.sub(r"[^A-Za-z0-9._-]+", "-", src.name)
dest = ROOT / "media" / name
if dest.resolve() != src:
    shutil.copy2(src, dest)
jid = uuid.uuid4().hex[:8]
(ROOT / "jobs").mkdir(exist_ok=True)
job = {"id": jid, "kind": a.kind, "title": a.title, "caption": caption, "video": f"media/{name}",
       "post_at": when.isoformat(), "status": "pending"}
(ROOT / "jobs" / f"{jid}.json").write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
git("add", "-A", "media", "jobs")
git("commit", "-q", "-m", f"add {a.kind} {jid}: {a.title}")
git("push", "-q")
print(f"queued {jid} for {when.isoformat()}")
