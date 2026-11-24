"""Send the day's post to Telegram for approval, and read the answer back.

  python telegram_preview.py --today        # preview today's row (IST)
  python telegram_preview.py --day 15       # preview a specific sheet day

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. The post job (post_from_github.py --require-approval)
uses approval_status() to see whether you tapped Approve or Skip.
"""
import argparse, csv, json, os, re, subprocess, sys, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT = os.environ.get('TELEGRAM_CHAT_ID', '')
API = f'https://api.telegram.org/bot{TOKEN}'


def tg(method, payload):
    data = urllib.parse.urlencode(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(f'{API}/{method}', data=data), timeout=60) as r:
        return json.load(r)


def send_text(text, buttons=None):
    p = {'chat_id': CHAT, 'text': text[:4000]}
    if buttons:
        p['reply_markup'] = json.dumps({'inline_keyboard': [buttons]})
    return tg('sendMessage', p)


def send_video(path, caption):
    out = subprocess.run(['curl', '-s', '-m', '300', f'{API}/sendVideo', '-F', f'chat_id={CHAT}',
                          '-F', f'video=@{path}', '-F', f'caption={caption}', '-F', 'supports_streaming=true'],
                         capture_output=True, text=True)
    return json.loads(out.stdout or '{}')


def approval_status(date_iso):
    """'approve', 'skip' or None, based on the latest button tap for this date."""
    try:
        updates = tg('getUpdates', {'limit': 100}).get('result', [])
    except Exception as e:
        print('getUpdates failed:', e)
        return None
    status = None
    for u in updates:
        cq = u.get('callback_query')
        if cq and str(cq['message']['chat']['id']) == str(CHAT):
            m = re.fullmatch(r'(approve|skip):(\d{4}-\d{2}-\d{2})', cq.get('data', ''))
            if m and m.group(2) == date_iso:
                status = m.group(1)
                try:
                    tg('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': 'Got it: ' + status})
                except Exception:
                    pass
    return status


def find_row(day=None, today=None):
    rows = list(csv.DictReader(open(os.path.join(ROOT, 'Daily-Post-Sheet.csv'), encoding='utf-8-sig')))
    if day:
        return next((r for r in rows if int(r['Day']) == day), None)
    return next((r for r in rows if r['Date'] == today), None)


def main():
    from post_from_github import ist_today
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', type=int)
    ap.add_argument('--today', action='store_true')
    a = ap.parse_args()
    row = find_row(a.day, ist_today()) if (a.day or a.today) else None
    if not row:
        print('No row to preview.'); return
    caption = f"{row['Cover text (hook)']}\n\n{row['Caption']}\n\n{row['Call to action']}\n\n{row['Hashtags']}"
    m = re.search(r'([\w\- ./]+\.mp4)', row['Media file'])
    date = row['Date']
    if not row['Format'].startswith('Reel') or not m:
        send_text(f"Heads up: {date} ({row['Weekday']}) is '{row['Format']}': {row['Media file']}\nThis one is posted by hand.")
        return
    path = os.path.join(ROOT, 'media', os.path.basename(m.group(1)).replace(' ', '-'))
    head = f"PREVIEW for {row['Weekday']} {date}, goes live 7:30 PM IST if you approve"
    if os.path.exists(path):
        r = send_video(path, head)
        if not r.get('ok'):
            send_text(head + f"\n(Video could not be sent to Telegram: {r.get('description')})")
    else:
        send_text(head + f"\nWARNING: video file missing in repo: {os.path.basename(path)}. It cannot be posted until uploaded.")
    send_text(f"Format: {row['Format']} | Pillar: {row['Pillar']}\n\nCAPTION:\n{caption}",
              [{'text': 'Approve', 'callback_data': f'approve:{date}'},
               {'text': 'Skip', 'callback_data': f'skip:{date}'}])
    print('preview sent for', date)


if __name__ == '__main__':
    main()
