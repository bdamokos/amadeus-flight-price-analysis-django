from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional

import typer
from amadeus import Client, ResponseError
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.style import Style
from rich.table import Table

console = Console()


class TripType(str, Enum):
    one_way = "one-way"
    return_trip = "return"


@dataclass(frozen=True)
class CheapestResult:
    origin: str
    destination: str
    currency: str
    trip_type: TripType
    departure_date: date
    return_date: Optional[date]
    total_price: Decimal
    raw_offer: dict[str, Any]


app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
    help="Find cheapest one-way or return flights using the Amadeus Flight Offers Search API.",
)


def _load_env() -> None:
    load_dotenv(override=False)
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env", override=False)


def _require_amadeus_env() -> None:
    missing = [k for k in ("AMADEUS_CLIENT_ID", "AMADEUS_CLIENT_SECRET") if not os.getenv(k)]
    if missing:
        raise typer.BadParameter(
            "Missing Amadeus credentials. Set env vars or create a .env in the repo root with: "
            + ", ".join(missing)
        )


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise typer.BadParameter("Date must be in YYYY-MM-DD format") from e


def _parse_iata(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise typer.BadParameter("Airport code must be a 3-letter IATA code (e.g. LHR)")
    return code


def _parse_trip(value: str) -> TripType:
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    if normalized in {"return", "round-trip", "roundtrip", "rt"}:
        return TripType.return_trip
    if normalized in {"one-way", "oneway", "ow"}:
        return TripType.one_way
    raise typer.BadParameter("Trip must be 'return' or 'one-way'")


def _iter_dates(start: date, end: date) -> Iterable[date]:
    if end < start:
        return
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _offer_total(offer: dict[str, Any]) -> Decimal:
    price = offer.get("price") or {}
    value = price.get("grandTotal") or price.get("total")
    if value is None:
        raise ValueError("Offer missing price.total / price.grandTotal")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as e:
        raise ValueError(f"Invalid price value: {value!r}") from e


def _cheapest_offer(client: Client, **kwargs: Any) -> tuple[Optional[Decimal], Optional[dict[str, Any]]]:
    response = client.shopping.flight_offers_search.get(**kwargs)
    if not response.data:
        return None, None
    cheapest = min(response.data, key=_offer_total)
    return _offer_total(cheapest), cheapest


def _maybe_sleep(throttle_seconds: float) -> None:
    if throttle_seconds and throttle_seconds > 0:
        time.sleep(throttle_seconds)


def _iter_requests(
    *,
    trip: TripType,
    departure_dates: Iterable[date],
    end_date: date,
    min_stay_days: int,
    max_stay_days: int,
) -> Iterable[tuple[date, Optional[date]]]:
    if trip == TripType.one_way:
        for departure_date in departure_dates:
            yield departure_date, None
        return

    for departure_date in departure_dates:
        earliest_return = departure_date + timedelta(days=min_stay_days)
        latest_return = min(end_date, departure_date + timedelta(days=max_stay_days))
        for return_date in _iter_dates(earliest_return, latest_return):
            yield departure_date, return_date


def _format_pair(departure_date: date, return_date: Optional[date]) -> str:
    if return_date:
        return f"{departure_date} / {return_date}"
    return f"{departure_date}"


def _update_top_n(
    top: list[CheapestResult],
    candidate: CheapestResult,
    top_n: int,
) -> bool:
    if top_n <= 0:
        return False
    top.append(candidate)
    top.sort(key=lambda r: r.total_price)
    if len(top) > top_n:
        del top[top_n:]
    return candidate in top


def _print_top_n(top: list[CheapestResult], *, top_n: int) -> None:
    if not top or top_n <= 0:
        return
    
    table = Table(title=f"Top {min(top_n, len(top))} results", show_header=True, header_style="bold magenta")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Dates", style="white")
    table.add_column("Price", justify="right", style="green")
    table.add_column("Offer ID", justify="right")

    for i, r in enumerate(top[:top_n], start=1):
        offer_id = str(r.raw_offer.get("id", ""))
        dates = _format_pair(r.departure_date, r.return_date)
        price_str = f"{r.total_price} {r.currency}"
        
        style = Style(bgcolor="dark_green", bold=True) if i == 1 else None
        
        table.add_row(
            str(i),
            dates,
            price_str,
            offer_id,
            style=style
        )
    
    console.print()
    console.print(table)


def _run_search(
    *,
    origin: str,
    destination: str,
    start_date: date,
    end_date: date,
    trip: TripType,
    min_stay_days: int,
    max_stay_days: int,
    adults: int,
    currency: str,
    nonstop: bool,
    max_offers: int,
    throttle_seconds: float,
    max_requests: int,
    force: bool,
    json_output: bool,
    verbose: bool,
    dry_run: bool,
    top_n: int,
    stream: bool,
) -> None:
    _load_env()
    _require_amadeus_env()

    if trip == TripType.one_way and (min_stay_days != 1 or max_stay_days != 14):
        typer.echo("Note: --min-stay/--max-stay are ignored for --trip one-way", err=True)

    if trip == TripType.return_trip and max_stay_days < min_stay_days:
        raise typer.BadParameter("--max-stay must be >= --min-stay")

    departure_dates = list(_iter_dates(start_date, end_date))
    if not departure_dates:
        raise typer.BadParameter("Empty date range")

    if trip == TripType.one_way:
        planned_requests = len(departure_dates)
    else:
        planned_requests = 0
        for departure_date in departure_dates:
            earliest_return = departure_date + timedelta(days=min_stay_days)
            latest_return = min(end_date, departure_date + timedelta(days=max_stay_days))
            planned_requests += max(0, (latest_return - earliest_return).days + 1)

    if planned_requests > max_requests and not force:
        raise typer.BadParameter(
            f"Planned {planned_requests} API requests (> {max_requests}). "
            "Narrow the date range / stay window, raise --max-requests, or pass --force."
        )

    if dry_run:
        typer.echo(json.dumps({"planned_requests": planned_requests, "trip": trip.value}, indent=2))
        return

    client = Client()

    best: Optional[CheapestResult] = None
    top: list[CheapestResult] = []
    completed = 0
    errors = 0

    def consider_result(
        departure_date: date,
        return_date: Optional[date],
        price: Decimal,
        offer: dict[str, Any],
    ) -> None:
        nonlocal best
        result = CheapestResult(
            origin=origin,
            destination=destination,
            currency=currency,
            trip_type=trip,
            departure_date=departure_date,
            return_date=return_date,
            total_price=price,
            raw_offer=offer,
        )
        is_new_best = best is None or result.total_price < best.total_price
        made_top = _update_top_n(top, result, top_n)

        if is_new_best:
            best = result
            console.print(
                f"[bold green]New best:[/bold green] {result.total_price} {result.currency} "
                f"({_format_pair(result.departure_date, result.return_date)})"
            )
        elif stream or (verbose and made_top):
            style = "dim" if not made_top else ""
            console.print(
                f"Found: {result.total_price} {result.currency} ({_format_pair(result.departure_date, result.return_date)})",
                style=style,
            )

    label = "Searching dates"
    requests_iter = _iter_requests(
        trip=trip,
        departure_dates=departure_dates,
        end_date=end_date,
        min_stay_days=min_stay_days,
        max_stay_days=max_stay_days,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(label, total=planned_requests)
        
        for departure_date, return_date in requests_iter:
            kwargs: dict[str, Any] = dict(
                originLocationCode=origin,
                destinationLocationCode=destination,
                departureDate=departure_date.isoformat(),
                adults=adults,
                currencyCode=currency,
                max=max_offers,
            )
            if return_date is not None:
                kwargs["returnDate"] = return_date.isoformat()
            if nonstop:
                kwargs["nonStop"] = "true"
            try:
                price, offer = _cheapest_offer(client, **kwargs)
                completed += 1
                if price is not None and offer is not None:
                    consider_result(departure_date, return_date, price, offer)
            except ResponseError as e:
                completed += 1
                errors += 1
                if verbose:
                    console.print(
                        f"[red]API error for {_format_pair(departure_date, return_date)}: {e}[/red]",
                    )
            _maybe_sleep(throttle_seconds)
            progress.update(task_id, advance=1)

    if best is None:
        typer.echo(
            json.dumps(
                {
                    "found": False,
                    "origin": origin,
                    "destination": destination,
                    "trip": trip.value,
                    "currency": currency,
                    "requests": {"planned": planned_requests, "completed": completed, "errors": errors},
                },
                indent=2,
            )
            if json_output
            else "No flights found for the given criteria."
        )
        raise typer.Exit(code=2)

    payload = {
        "found": True,
        "origin": best.origin,
        "destination": best.destination,
        "trip": best.trip_type.value,
        "currency": best.currency,
        "departure_date": best.departure_date.isoformat(),
        "return_date": best.return_date.isoformat() if best.return_date else None,
        "total_price": str(best.total_price),
        "requests": {"planned": planned_requests, "completed": completed, "errors": errors},
    }
    if top_n > 0:
        payload["top"] = [
            {
                "departure_date": r.departure_date.isoformat(),
                "return_date": r.return_date.isoformat() if r.return_date else None,
                "total_price": str(r.total_price),
                "offer_id": r.raw_offer.get("id"),
            }
            for r in top[:top_n]
        ]

    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        _print_top_n(top, top_n=top_n)
        
        result_text = ""
        if best.return_date:
            result_text = (
                f"Best return: {best.origin}->{best.destination}\n"
                f"{best.departure_date} / {best.return_date}\n"
                f"[bold green]= {best.total_price} {best.currency}[/bold green]\n"
                f"({completed}/{planned_requests} requests, {errors} errors)"
            )
        else:
            result_text = (
                f"Best one-way: {best.origin}->{best.destination}\n"
                f"{best.departure_date}\n"
                f"[bold green]= {best.total_price} {best.currency}[/bold green]\n"
                f"({completed}/{planned_requests} requests, {errors} errors)"
            )
        
        console.print(Panel(result_text, title="Search Complete", border_style="green", expand=False))


@app.callback()
def main(ctx: typer.Context) -> None:
    """Interactive mode when no subcommand is provided."""
    if ctx.invoked_subcommand is not None:
        return

    origin = typer.prompt("Origin IATA code", value_proc=_parse_iata)
    destination = typer.prompt("Destination IATA code", value_proc=_parse_iata)
    start_date = typer.prompt("Start date (YYYY-MM-DD)", value_proc=_parse_date)
    end_date = typer.prompt("End date (YYYY-MM-DD)", value_proc=_parse_date)
    trip = typer.prompt("Trip type (return/one-way)", default="return", value_proc=_parse_trip)

    min_stay = 1
    max_stay = 14
    if trip == TripType.return_trip:
        min_stay = typer.prompt("Minimum stay (days)", default=3, value_proc=int)
        max_stay = typer.prompt("Maximum stay (days)", default=10, value_proc=int)

    adults = typer.prompt("Adults", default=1, value_proc=int)
    currency = typer.prompt("Currency", default="USD").strip().upper()
    nonstop = typer.confirm("Non-stop only?", default=False)
    top_n = typer.prompt("Show top N results", default=5, value_proc=int)
    stream = typer.confirm("Print results as they come in?", default=False)

    _run_search(
        origin=origin,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        trip=trip,
        min_stay_days=min_stay,
        max_stay_days=max_stay,
        adults=adults,
        currency=currency,
        nonstop=nonstop,
        max_offers=10,
        throttle_seconds=0.0,
        max_requests=200,
        force=False,
        json_output=False,
        verbose=True,
        dry_run=False,
        top_n=top_n,
        stream=stream,
    )


@app.command()
def search(
    origin: Optional[str] = typer.Argument(None, help="Origin IATA airport code (e.g. LHR)."),
    destination: Optional[str] = typer.Argument(None, help="Destination IATA airport code (e.g. JFK)."),
    start: Optional[str] = typer.Option(None, "--start", help="Start date (YYYY-MM-DD)."),
    end: Optional[str] = typer.Option(None, "--end", help="End date (YYYY-MM-DD)."),
    trip: TripType = typer.Option(TripType.return_trip, "--trip", case_sensitive=False),
    min_stay_days: int = typer.Option(1, "--min-stay", min=0, help="Minimum stay length (return trips)."),
    max_stay_days: int = typer.Option(14, "--max-stay", min=0, help="Maximum stay length (return trips)."),
    adults: int = typer.Option(1, "--adults", min=1),
    currency: str = typer.Option("USD", "--currency"),
    nonstop: bool = typer.Option(False, "--nonstop", help="Only consider direct flights."),
    max_offers: int = typer.Option(10, "--max-offers", min=1, help="Max offers per API response."),
    throttle_seconds: float = typer.Option(0.0, "--throttle", help="Sleep between API requests (seconds)."),
    max_requests: int = typer.Option(200, "--max-requests", min=1, help="Hard cap on API requests."),
    force: bool = typer.Option(False, "--force", help="Allow exceeding --max-requests."),
    json_output: bool = typer.Option(False, "--json", help="Output result as JSON."),
    verbose: bool = typer.Option(False, "--verbose", help="Print notable intermediate results."),
    stream: bool = typer.Option(False, "--stream", help="Print each result as it is fetched (can be noisy)."),
    top_n: int = typer.Option(5, "--top", min=0, help="Show the top N results (runner-ups)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned request count, do not call the API."),
) -> None:
    """
    Searches all dates in [start, end] to find the cheapest one-way date or cheapest departure/return combo.
    Any missing required fields will be prompted for interactively.
    """
    origin_code = _parse_iata(origin) if origin else typer.prompt("Origin IATA code", value_proc=_parse_iata)
    destination_code = (
        _parse_iata(destination) if destination else typer.prompt("Destination IATA code", value_proc=_parse_iata)
    )
    start_date = _parse_date(start) if start else typer.prompt("Start date (YYYY-MM-DD)", value_proc=_parse_date)
    end_date = _parse_date(end) if end else typer.prompt("End date (YYYY-MM-DD)", value_proc=_parse_date)

    _run_search(
        origin=origin_code,
        destination=destination_code,
        start_date=start_date,
        end_date=end_date,
        trip=trip,
        min_stay_days=min_stay_days,
        max_stay_days=max_stay_days,
        adults=adults,
        currency=currency.strip().upper(),
        nonstop=nonstop,
        max_offers=max_offers,
        throttle_seconds=throttle_seconds,
        max_requests=max_requests,
        force=force,
        json_output=json_output,
        verbose=verbose,
        dry_run=dry_run,
        top_n=top_n,
        stream=stream,
    )
