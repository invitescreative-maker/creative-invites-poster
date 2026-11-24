"""Post a Reel (or Story) to Instagram using a public GitHub video URL.

  python post_from_github.py --today            # dry run for today's row (IST)
  python post_from_github.py --day 1 --publish  # publish the row for sheet day 1
  python post_from_github.py --story media/x.mp4 --publish

Secrets come from environment variables IG_ACCESS_TOKEN and IG_USER_ID
(GitHub Actions secrets). Videos live in media/ and are fetched by Instagram from
https://raw.githubusercontent.com/<repo>/main/media/<name with spaces as dashes>.
"""
import argparse, csv, datetime, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

API = 'https://graph.facebook.com/v21.0'
REPO = os.environ.get('GITHUB_REPOSITORY', 'invitescreative-maker/creative-invites-poster')
ROOT = os.path.dirname(os.path.abspath(__file__))


def ist_today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).date().isoformat()


def call(method, url, data=None):
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f'API error {e.code}: {e.read().decode("utf-8", "replace")[:500]}')


def raw_url(media_path):
    name = os.path.basename(media_path).replace(' ', '-')
    return f'https://raw.githubusercontent.com/{REPO}/main/media/{urllib.parse.quote(name)}'


def publish(video_url, caption, token, uid, story=False):
    p = {'media_type': 'STORIES' if story else 'REELS', 'video_url': video_url, 'access_token': token}
    if not story:
        p.update({'caption': caption, 'share_to_feed': 'true'})
    cid = call('POST', f'{API}/{uid}/media', urllib.parse.urlencode(p).encode())['id']
    print('container', cid)
    for _ in range(90):
        s = call('GET', f'{API}/{cid}?fields=status_code,status&access_token=' + urllib.parse.quote(token))
        print('status', s.get('status_code'), s.get('status', ''))
        if s.get('status_code') == 'FINISHED':
            break
        if s.get('status_code') in ('ERROR', 'EXPIRED'):
            raise SystemExit(f'Processing failed: {s}')
        time.sleep(10)
    else:
        raise SystemExit('Timed out waiting for processing')
    r = call('POST', f'{API}/{uid}/media_publish', urllib.parse.urlencode({'creation_id': cid, 'access_token': token}).encode())
    print('PUBLISHED media id', r['id'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', type=int)
    ap.add_argument('--today', action='store_true')
    ap.add_argument('--story')
    ap.add_argument('--publish', action='store_true')
    ap.add_argument('--require-approval', action='store_true', help='only post if approved on Telegram')
    a = ap.parse_args()
    token, uid = os.environ.get('IG_ACCESS_TOKEN', ''), os.environ.get('IG_USER_ID', '')
    if a.story:
        url = raw_url(a.story)
        print('Story video URL:', url)
        if a.publish:
            publish(url, '', token, uid, story=True)
        return
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'Daily-Post-Sheet.csv'), encoding='utf-8-sig')))
    if a.today:
        row = next((r for r in rows if r['Date'] == ist_today()), None)
        if not row:
            print('No row for', ist_today()); return
    elif a.day:
        row = next((r for r in rows if int(r['Day']) == a.day), None)
        if not row:
            raise SystemExit(f'No row for day {a.day}')
    else:
        raise SystemExit('Use --day N or --today')
    caption = f"{row['Cover text (hook)']}\n\n{row['Caption']}\n\n{row['Call to action']}\n\n{row['Hashtags']}"
    m = re.search(r'([\w\- ./]+\.mp4)', row['Media file'])
    print(f"Day {row['Day']} | {row['Date']} | {row['Format']} | {row['Media file']}")
    if not row['Format'].startswith('Reel') or not m:
        print('Not an automatic reel row (post by hand). Nothing to do.'); return
    url = raw_url(m.group(1))
    print('Video URL:', url); print('--- caption ---'); print(caption); print('---------------')
    if not a.publish:
        print('DRY RUN only. Add --publish to post.'); return
    if a.require_approval:
        import telegram_preview as tp
        status = tp.approval_status(row['Date'])
        if status != 'approve':
            msg = 'You skipped' if status == 'skip' else 'No approval received for'
            print(f'{msg} {row["Date"]}: not posting.')
            tp.send_text(f'{msg} the {row["Date"]} post, so nothing was posted today.')
            return
    publish(url, caption, token, uid)
    if a.require_approval:
        tp.send_text(f'Posted to Instagram: {row["Cover text (hook)"]}')


if __name__ == '__main__':
    main()
