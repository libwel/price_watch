# pricewatch_async\watcher.py
import asyncio, datetime, pathlib, sys, logging, typer, aiohttp, aiosqlite
from rich.console import Console
from rich.table import Table
from win10toast import ToastNotifier  # ← 無効にしたい場合は try/except でも可

from bs4 import BeautifulSoup

APP = typer.Typer(help="Async price watcher with alert")
DB_PATH = pathlib.Path("price.db")
console = Console()
toaster = ToastNotifier()

DEFAULT_URLS = [
    "http://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
    "http://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html",
]

# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("watch.log", "a", "utf-8"),
              logging.StreamHandler(sys.stdout)],
)

# ---------- SCRAPER ----------
async def fetch_price(session: aiohttp.ClientSession, url: str) -> float | None:
    try:
        async with session.get(url, timeout=10) as r:
            r.raise_for_status()
            r.encoding = "utf-8"
            html = await r.text()
    except Exception as e:
        logging.warning("Request error %s → %s", url, e)
        return None

    soup = BeautifulSoup(html, "html.parser")
    tag = soup.select_one("p.price_color")  # ex) £53.74
    return float(tag.text.lstrip("£")) if tag else None

# ---------- DB ----------
CREATE_SQL = "CREATE TABLE IF NOT EXISTS prices(ts TEXT, url TEXT, price REAL)"
INSERT_SQL = "INSERT INTO prices VALUES (?,?,?)"
SELECT_DIFF_SQL = """
SELECT price FROM prices
WHERE url = ?
ORDER BY ts DESC
LIMIT 2
"""

async def save_rows(rows: list[tuple[str, str, float | None]]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_SQL)
        await db.executemany(INSERT_SQL, rows)
        await db.commit()

async def latest_two(url: str) -> list[float]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(SELECT_DIFF_SQL, (url,)) as cur:
            return [r[0] for r in await cur.fetchall()]

# ---------- MAIN ----------
@APP.command()
def run(
    urls: list[str] = typer.Argument(None, help="商品 URL を複数指定"),
    threshold: float = typer.Option(5.0, "--th", help="下落率％（超えたら通知）")
):
    """全 URL を並列取得 → 価格保存 → 直近２件で％変動を計算"""
    target_urls =  DEFAULT_URLS
    asyncio.run(main(target_urls, threshold))

async def main(urls: list[str], threshold: float):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    async with aiohttp.ClientSession() as sess:
        prices = await asyncio.gather(*(fetch_price(sess, u) for u in urls))

    rows = [(ts, u, p) for u, p in zip(urls, prices)]
    await save_rows(rows)

    # ---- 表示 ----
    table = Table(title=f"Price @ {ts}")
    table.add_column("URL", overflow="fold")
    table.add_column("£ Now", justify="right")
    table.add_column("Δ％", justify="right")
    alerts = []
    for (u, now) in zip(urls, prices):
        prevs = await latest_two(u)
        delta = ""
        if len(prevs) == 2 and prevs[1]:
            delta_val = (now - prevs[1]) / prevs[1] * 100
            delta = f"{delta_val:+.1f}%"
            if delta_val <= -threshold:
                alerts.append((u, now, delta_val))
        table.add_row(u, f"{now:.2f}" if now else "N/A", delta)
    console.print(table)

    # ---- 通知 ----
    for u, price, d in alerts:
        msg = f"Price drop {d:.1f}%  (£{price:.2f})\n{u}"
        logging.info("ALERT: %s", msg)
        try:
            toaster.show_toast("Price Watch Alert", msg, threaded=True, duration=5)
        except Exception:
            pass  # 通知失敗は無視

if __name__ == "__main__":
    sys.exit(APP())