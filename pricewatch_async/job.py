# pricewatch_async\job.py
import schedule, time, subprocess, sys, pathlib

# 1 日 1 回 09:00 実行（UTC→JST は +9h。GitHub Actions は UTC）
schedule.every().day.at("00:00").do(
    lambda: subprocess.run(
        [sys.executable, "-m", "pricewatch_async.watcher", "run"], check=True)
)

print("Scheduler started. Press Ctrl+C to stop.")
while True:
    schedule.run_pending()
    time.sleep(30)