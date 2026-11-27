# creative-invites-poster
Posting for @thecreativeinvites, same workflow as the Decoded Bharat autopost. GitHub Actions runs it, so the PC can be off.

- `jobs/<id>.json`  one file per post (pending -> scheduled -> posting -> posted / failed / needs_changes / discarded)
- `media/`          videos (public: Instagram fetches them from here)
- `add_job.py`      queue a post; `poster.py` previews on Telegram, reads taps and posts; `waiter.py` keeps it awake
- Telegram buttons: Approve, Post now, Needs changes, Discard. Nothing posts without approval.

Secrets (Settings > Secrets and variables > Actions): IG_ACCESS_TOKEN, IG_USER_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
Never commit tokens. This repo is public.
`Daily-Post-Sheet.csv` is only a planning reference now.
