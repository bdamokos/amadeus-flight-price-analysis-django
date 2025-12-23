# flight-price-cli

Small Typer-based CLI for finding the cheapest one-way date or departure/return date combination using the Amadeus Flight Offers Search API.

## Setup

The CLI reuses the same environment variables as the Django app:

- `AMADEUS_CLIENT_ID`
- `AMADEUS_CLIENT_SECRET`
- `AMADEUS_HOSTNAME` (`test` or `production`)

It loads `.env` from the repo root if present.

Install dependencies (adds `typer`):

```bash
pip install -r requirements.txt
```

## Usage

Fully interactive (prompts for everything):

```bash
python -m cli.flight_price_cli
```

One-way cheapest day in a range:

```bash
python -m cli.flight_price_cli search LHR JFK --trip one-way --start 2026-01-10 --end 2026-01-25
```

Return trip cheapest combination (constrained by stay length):

```bash
python -m cli.flight_price_cli search LHR JFK --trip return --start 2026-01-10 --end 2026-01-25 --min-stay 3 --max-stay 10
```

Count how many requests would be made (no API calls):

```bash
python -m cli.flight_price_cli search LHR JFK --trip return --start 2026-01-10 --end 2026-02-10 --dry-run
```

If you omit required values, the `search` command will prompt for them too:

```bash
python -m cli.flight_price_cli search
```
