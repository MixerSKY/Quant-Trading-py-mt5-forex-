import os
import time
import pandas as pd
from datetime import datetime
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.console import Console
from rich.align import Align
from rich.text import Text
from rich.columns import Columns

# --- KONFIGURACJA FLOTY (MAPA DROGOWA) ---
FLEET = {
    "US500": "./US500/live_trade_journal_US500.csv",
    "EURUSD": "./EURUSD/live_trade_journal_EURUSD.csv",
    "GBPJPY": "./GBPJPY/live_trade_journal_GBPJPY.csv",
    "NZDUSD": "./NZDUSD/live_trade_journal_NZDUSD.csv",
    "GER40": "./GER40/live_trade_journal_DE40.csv",
    # Mozna dodawac ile sie da
}

INITIAL_BALANCE = 10000.0
console = Console()

def fetch_bot_stats(symbol, filepath):
    stats = {
        "symbol": symbol, "status": "[red]OFFLINE[/red]", "daily_pnl": 0.0, 
        "total_pnl": 0.0, "winrate": 0.0, "trades": 0, "last_trade": "Brak"
    }
    
    if not os.path.exists(filepath):
        stats["status"] = "[red]BRAK PLIKU[/red]"
        return stats
        
    try:
        df = pd.read_csv(filepath)
        if df.empty:
            stats["status"] = "[yellow]OCZEKUJE NA TRADE[/yellow]"
            return stats
            
        stats["status"] = "[bold green]ONLINE (AKTYWNY)[/bold green]"
        last_row = df.iloc[-1]
        
        stats["daily_pnl"] = float(last_row.get('Daily_PnL', 0.0))
        stats["total_pnl"] = float(last_row.get('Balance_After', INITIAL_BALANCE)) - INITIAL_BALANCE
        
        wins = len(df[df['PnL'] > 0])
        stats["trades"] = len(df)
        stats["winrate"] = round((wins / stats["trades"]) * 100, 1) if stats["trades"] > 0 else 0.0
        
        last_pnl = float(last_row['PnL'])
        color = "green" if last_pnl > 0 else "red"
        sign = "+" if last_pnl > 0 else ""
        stats["last_trade"] = f"[{color}]{last_row['Type']} | {sign}{last_pnl:.2f}$[/{color}]"
        
    except Exception:
        stats["status"] = "[red]BŁĄD ODCZYTU CSV[/red]"
        
    return stats

def generate_dashboard():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main")
    )
    
    global_total_pnl = 0.0
    global_daily_pnl = 0.0
    panels = []
    
    for symbol, filepath in FLEET.items():
        data = fetch_bot_stats(symbol, filepath)
        
        dpnl_color = "green" if data["daily_pnl"] >= 0 else "red"
        tpnl_color = "green" if data["total_pnl"] >= 0 else "red"
        
        global_total_pnl += data["total_pnl"]
        global_daily_pnl += data["daily_pnl"]
        
        table = Table(show_header=False, expand=True, box=None)
        table.add_column("Key", style="cyan", width=14)
        table.add_column("Value", justify="right")
        
        table.add_row("Status silnika:", data["status"])
        table.add_row("Ilość zagrań:", str(data["trades"]))
        table.add_row("Skuteczność:", f"{data['winrate']}%")
        table.add_row("Ostatnia akcja:", data["last_trade"])
        table.add_row("---", "---")
        table.add_row("Daily PnL:", f"[{dpnl_color}]{data['daily_pnl']:.2f}$[/{dpnl_color}]")
        table.add_row("Total PnL:", f"[{tpnl_color}]{data['total_pnl']:.2f}$[/{tpnl_color}]")
        
        daily_loss_pct = abs(min(0, data["daily_pnl"])) / 400.0 * 100
        guard_color = "green" if daily_loss_pct < 50 else ("yellow" if daily_loss_pct < 80 else "bold red")
        table.add_row("Daily Guard:", f"[{guard_color}]{daily_loss_pct:.1f}% z -400$[/{guard_color}]")
        
        # Tworzenie pojedynczego kafelka ze stałą szerokością
        panel = Panel(
            Align.center(table, vertical="middle"), 
            title=f"[bold white] {symbol} [/bold white]", 
            border_style="cyan",
            width=38 # Stała szerokość gwarantuje idealną siatkę
        )
        panels.append(panel)
        
    # Renderowanie siatki (Kafelki same zawiną się do nowej linii)
    grid = Columns(panels, expand=True)
    layout["main"].update(grid)
        
    # Aktualizacja nagłówka z globalnymi statystykami
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    g_tpnl_color = "green" if global_total_pnl >= 0 else "red"
    header_text = Text(f"📡 QUANT FLEET COMMANDER | Czas: {current_time} | Global PnL: ", style="bold cyan")
    header_text.append(f"{global_total_pnl:.2f}$", style=f"bold {g_tpnl_color}")
    layout["header"].update(Panel(header_text, style="blue"))
        
    return layout

if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear')
    try:
        with Live(generate_dashboard(), refresh_per_second=2, screen=True) as live:
            while True:
                time.sleep(2)
                live.update(generate_dashboard())
    except KeyboardInterrupt:
        console.print("[bold red]Zatrzymano podgląd Dashboardu.[/bold red]")