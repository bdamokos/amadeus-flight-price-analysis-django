
from datetime import date
from decimal import Decimal
from cli.flight_price_cli.app import _print_top_n, CheapestResult, TripType, console
from rich.panel import Panel

def test_ui():
    print("Testing Rich UI components...")
    
    # Test 1: Table
    print("\n--- Testing Top N Table ---")
    results = [
        CheapestResult(
            origin="LHR", destination="JFK", currency="USD", trip_type=TripType.return_trip,
            departure_date=date(2024, 6, 1), return_date=date(2024, 6, 10),
            total_price=Decimal("500.00"), raw_offer={"id": "offer1"}
        ),
        CheapestResult(
            origin="LHR", destination="JFK", currency="USD", trip_type=TripType.return_trip,
            departure_date=date(2024, 6, 2), return_date=date(2024, 6, 12),
            total_price=Decimal("550.00"), raw_offer={"id": "offer2"}
        ),
        CheapestResult(
            origin="LHR", destination="JFK", currency="USD", trip_type=TripType.return_trip,
            departure_date=date(2024, 6, 3), return_date=date(2024, 6, 13),
            total_price=Decimal("600.00"), raw_offer={"id": "offer3"}
        ),
    ]
    _print_top_n(results, top_n=5)
    
    # Test 2: Final Panel
    print("\n--- Testing Final Panel ---")
    best = results[0]
    result_text = (
        f"Best return: {best.origin}->{best.destination}\n"
        f"{best.departure_date} / {best.return_date}\n"
        f"[bold green]= {best.total_price} {best.currency}[/bold green]\n"
        f"(10/10 requests, 0 errors)"
    )
    console.print(Panel(result_text, title="Search Complete", border_style="green", expand=False))

if __name__ == "__main__":
    test_ui()
