import asyncio
import requests
import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime

ACCOUNTS_FILE = "konta.txt"  # Format: email:haslo (każde konto w nowej linii)
OUTPUT_FILE = "wyniki.txt"

def load_accounts(filepath):
    """Wczytuje konta z pliku txt w formacie email:haslo"""
    accounts = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):  # Pomija puste linie i komentarze
                    continue
                if ':' not in line:
                    print(f"⚠️  Błędny format w linii {line_num}: {line}")
                    continue
                email, password = line.split(':', 1)
                accounts.append({'email': email.strip(), 'password': password.strip()})
        return accounts
    except FileNotFoundError:
        print(f"❌ Nie znaleziono pliku: {filepath}")
        print(f"Utwórz plik '{filepath}' z kontami w formacie: email:haslo")
        return []

async def scrape_account(email, password):
    """Pobiera dane dla jednego konta"""
    print(f"\n🔄 Przetwarzanie konta: {email}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, slow_mo=250)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto("https://sklep.ebilet.pl/LoginRegister", wait_until="domcontentloaded")

            # Akceptacja ciasteczek
            try:
                btn = page.locator("button:has-text('Akceptuj'), button:has-text('Zezwól')")
                if await btn.count() > 0:
                    await btn.first.click()
                    await page.wait_for_timeout(1000)
            except:
                pass

            # Logowanie
            await page.fill("#loginRegisterForm-email-input", email)
            await page.fill("#loginRegisterForm-password-input", password)
            if await page.locator("#loginRegisterForm-login-button").count() > 0:
                await page.click("#loginRegisterForm-login-button")
            else:
                await page.press("#loginRegisterForm-password-input", "Enter")
            await page.wait_for_timeout(8000)

            # Pobranie ciasteczek z przeglądarki
            cookies = await context.cookies()
            cookie_jar = {cookie["name"]: cookie["value"] for cookie in cookies}

        finally:
            await browser.close()  # POPRAWKA: dodano await

    # Teraz używamy requests
    url = "https://sklep.ebilet.pl/api/customer/getcustomertransactionsdetails?page=1&pageSize=100"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
    }

    resp = requests.get(url, headers=headers, cookies=cookie_jar)
    
    if resp.status_code != 200:
        print(f"❌ Błąd pobierania danych dla {email}: HTTP {resp.status_code}")
        return None
    
    try:
        data = resp.json()
    except:
        print(f"❌ Błąd parsowania JSON dla {email}")
        return None

    transactions = data.get("tr", [])
    
    if not transactions:
        print(f"ℹ️  Brak transakcji dla {email}")
        return []
    
    rows = []
    for tr in transactions:
        base = {
            "Data transakcji": tr.get("d"),
            "Status": tr.get("s"),
            "Kwota": tr.get("p"),
        }
        for ticket in tr.get("te", []):
            row = base.copy()
            row["Wydarzenie"] = ticket.get("e")
            row["Miasto"] = ticket.get("c")
            row["Data wydarzenia"] = ticket.get("d")
            rows.append(row)

    print(f"✅ Pobrano {len(rows)} biletów dla {email}")
    return rows

def format_results(email, password, transactions):
    """Formatuje wyniki dla jednego konta"""
    result = f"{email}:{password}\n"
    
    if not transactions:
        result += "Brak transakcji\n\n"
    else:
        # Nagłówki kolumn
        result += f"{'Data transakcji':<20} {'Status':<15} {'Kwota':<10} {'Wydarzenie':<50} {'Miasto':<20} {'Data wydarzenia':<20}\n"
        result += "-" * 135 + "\n"
        
        # Wiersze z danymi
        for tr in transactions:
            data_tr = (tr.get('Data transakcji') or '')[:19]  # Obcięcie do rozmiaru
            status = (tr.get('Status') or '')[:14]
            kwota = str(tr.get('Kwota') or '')[:9]
            wydarzenie = (tr.get('Wydarzenie') or '')[:49]
            miasto = (tr.get('Miasto') or '')[:19]
            data_wyd = (tr.get('Data wydarzenia') or '')[:19]
            
            result += f"{data_tr:<20} {status:<15} {kwota:<10} {wydarzenie:<50} {miasto:<20} {data_wyd:<20}\n"
    
    result += "\n"
    return result

async def main():
    # Wczytanie kont
    accounts = load_accounts(ACCOUNTS_FILE)
    
    if not accounts:
        print("\n❌ Brak kont do przetworzenia!")
        return
    
    print(f"📋 Znaleziono {len(accounts)} kont do przetworzenia")
    
    # Utworzenie pliku wyników na początku
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"=== Wyniki pobierania biletów z eBilet ===\n")
        f.write(f"Data wygenerowania: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 50 + "\n\n")
    
    # Przetwarzanie każdego konta i dopisywanie na bieżąco
    for account in accounts:
        email = account['email']
        password = account['password']
        
        transactions = await scrape_account(email, password)
        
        # Zabezpieczenie przed None
        if transactions is None:
            transactions = []
        
        # Natychmiastowy zapis do pliku
        formatted = format_results(email, password, transactions)
        with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
            f.write(formatted)
    
    print(f"\n💾 Zapisano wyniki do pliku: {OUTPUT_FILE}")
    print(f"📊 Przetworzono {len(accounts)} kont")

if __name__ == "__main__":
    asyncio.run(main())