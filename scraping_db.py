# -*- coding: utf-8 -*-

import os
import re
import time
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client, Client

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Supabase config (injected by GitHub Actions secrets) ──────────────────────

SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]

SETS_TABLE:   str = "tcg_sets"
PRICES_TABLE: str = "tcg_card_prices"

# ── Sets to scrape ─────────────────────────────────────────────────────────────

SETS_TO_SCRAPE = [
    {
        "set_name": "Premium Booster -The Best- Vol. 2",
        "set_code": "PRB02",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/premium-booster-the-best-vol-2",
    },
    {
        "set_name": "Legacy of the Master",
        "set_code": "OP12",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/legacy-of-the-master",
    },
    {
        "set_name": "A Fist of Divine Speed",
        "set_code": "OP11",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/a-fist-of-divine-speed",
    },
    {
        "set_name": "Royal Blood",
        "set_code": "OP10",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/royal-blood",
    },
    {
        "set_name": "Emperors in the New World",
        "set_code": "OP09",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/emperors-in-the-new-world",
    },
    {
        "set_name": "Carrying On His Will",
        "set_code": "OP13",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/carrying-on-his-will",
    },
    {
        "set_name": "Extra Booster: Anime 25th Collection Guide",
        "set_code": "EB02",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/extra-booster-anime-25th-collection",
    },
    {
        "set_name": "Extra Booster: One Piece Heroines Edition",
        "set_code": "EB03",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/extra-booster-one-piece-heroines-edition",
    },
    {
        "set_name": "The Azure Seas Seven",
        "set_code": "OP14",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/the-azure-seas-seven",
    },
    {
        "set_name": "Adventure on Kami's Island",
        "set_code": "OP15",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/adventure-on-kamis-island",
    },
    {
        "set_name": "The Time of Battle",
        "set_code": "OP16",
        "url": "https://www.tcgplayer.com/categories/trading-and-collectible-card-games/one-piece-card-game/price-guides/the-time-of-battle",
    },
]

# ── Selenium parameters ────────────────────────────────────────────────────────

PAGE_LOAD_TIMEOUT = 60
SCROLL_PAUSE      = 2
BATCH_SIZE        = 500


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class SetRecord:
    set_name: str
    set_code: str
    url:      str


@dataclass
class CardPrice:
    set_code:     str
    product_name: str
    card_number:  Optional[str]
    printing:     Optional[str]
    condition:    Optional[str]
    rarity:       Optional[str]
    market_price: Optional[float]


# ── Driver ─────────────────────────────────────────────────────────────────────

def build_driver() -> webdriver.Chrome:
    """Headless Chrome with anti-bot-detection hardening."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    # UA version matches the Chrome installed in the Actions runner
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    )

    # Suppress the navigator.webdriver fingerprint TCGPlayer checks for
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)

    # Patch navigator.webdriver at the JS level for belt-and-suspenders coverage
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


# ── Helpers ────────────────────────────────────────────────────────────────────

def scroll_to_bottom(driver: webdriver.Chrome) -> None:
    """Scroll until the page stops growing (handles virtual/lazy-loaded tables)."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        log.info("  Scrolled → page height %d px", new_height)


def parse_price(raw: str) -> Optional[float]:
    """Strip non-numeric characters and return float, or None on failure."""
    clean = re.sub(r"[^\d.]", "", raw)
    try:
        return float(clean) if clean else None
    except ValueError:
        return None


def cell_text(cells: list, index: int) -> Optional[str]:
    """Return stripped text from a <td> by index, or None if missing/empty."""
    if index < len(cells):
        val = cells[index].text.strip()
        return val if val else None
    return None


# ── Scraper ────────────────────────────────────────────────────────────────────

def scrape_set(set_record: SetRecord) -> list[CardPrice]:
    """
    Scrape all card rows from one TCGPlayer price-guide page.

    TCGPlayer table column order:
        0: checkbox  1: image  2: product name  3: printing
        4: condition  5: rarity  6: card number  7: market price
    """
    driver  = build_driver()
    results: list[CardPrice] = []

    try:
        log.info("Scraping: %s", set_record.set_name)
        driver.get(set_record.url)

        # Give the SPA JS time to bootstrap, then emit diagnostics so any
        # future timeout is immediately debuggable from the Actions log
        time.sleep(5)
        log.info("  Page title: %s", driver.title)
        log.info("  Page source snippet:\n%s", driver.page_source[:2000])

        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, "tbody.tcg-table-body tr")
            )
        )
        time.sleep(3)
        scroll_to_bottom(driver)
        time.sleep(2)

        rows = driver.find_elements(By.CSS_SELECTOR, "tbody.tcg-table-body tr")
        log.info("  Found %d candidate rows", len(rows))

        for row in rows:
            try:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 6:
                    continue

                product_name = cell_text(cells, 2)
                if not product_name:
                    continue

                results.append(
                    CardPrice(
                        set_code=set_record.set_code,
                        product_name=product_name,
                        printing=cell_text(cells, 3),
                        condition=cell_text(cells, 4),
                        rarity=cell_text(cells, 5),
                        card_number=cell_text(cells, 6),
                        market_price=parse_price(cell_text(cells, 7) or ""),
                    )
                )
            except Exception as e:
                log.warning("  Skipping row: %s", e)

    finally:
        driver.quit()

    log.info("  Scraped %d card entries", len(results))
    return results


# ── Supabase helpers ───────────────────────────────────────────────────────────

def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set as environment variables.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upsert_set(client: Client, set_record: SetRecord) -> str:
    """Insert or update the set row; set_code is the unique conflict key."""
    client.table(SETS_TABLE).upsert(
        {
            "set_name": set_record.set_name,
            "set_code": set_record.set_code,
            "url":      set_record.url,
        },
        on_conflict="set_code",
    ).execute()
    log.info("  Set '%s' → set_code='%s'", set_record.set_name, set_record.set_code)
    return set_record.set_code


def insert_prices(client: Client, cards: list[CardPrice]) -> None:
    if not cards:
        log.warning("  No card prices to insert.")
        return

    records = [
        {
            "set_code":     c.set_code,
            "product_name": c.product_name,
            "card_number":  c.card_number,
            "printing":     c.printing,
            "condition":    c.condition,
            "rarity":       c.rarity,
            "market_price": c.market_price,
        }
        for c in cards
    ]

    for i in range(0, len(records), BATCH_SIZE):
        chunk = records[i : i + BATCH_SIZE]
        client.table(PRICES_TABLE).insert(chunk).execute()
        log.info("  Inserted rows %d–%d", i + 1, i + len(chunk))

    log.info("%d rows inserted into '%s'", len(records), PRICES_TABLE)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    for set_cfg in SETS_TO_SCRAPE:
        set_record = SetRecord(**set_cfg)
        client     = get_client()

        upsert_set(client, set_record)

        cards = scrape_set(set_record)
        if not cards:
            log.error("  No data scraped for %s — skipping.", set_record.set_name)
            continue

        df = pd.DataFrame([c.__dict__ for c in cards])
        csv_filename = f"{set_record.set_code}.csv"
        df.to_csv(csv_filename, index=False)
        log.info("  Saved %d rows to %s", len(df), csv_filename)

        for c in cards[:3]:
            log.info("  Sample: %s", c)

        insert_prices(client, cards)
        time.sleep(7)

    log.info("All sets complete.")


if __name__ == "__main__":
    main()
