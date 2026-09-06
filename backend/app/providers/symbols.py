"""Symbol registry: NSE symbols, their sector, and benchmark mapping.

Deliberately a static table rather than a database collection. The universe
is small and stable, it needs no migration, and a bundled table means symbol
search keeps working even when every external provider is down.
"""

from __future__ import annotations

from dataclasses import dataclass

BENCHMARK_SYMBOL = "NIFTY50"


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str  # canonical NSE symbol, e.g. "TCS"
    name: str  # display name
    sector: str  # sector key, maps into SECTOR_INDICES
    yahoo: str  # yfinance ticker
    is_index: bool = False


# Sector index tickers on Yahoo Finance. Only widely-available ones are used;
# a missing sector degrades to benchmark-only comparison.
# Sector indices, addressed by CANONICAL symbol like every other instrument.
# Using Yahoo tickers as identifiers here previously meant the demo provider had
# no entry for "^NSEBANK" and silently produced random sector data.
SECTOR_INDICES: dict[str, tuple[str, str]] = {
    # sector key -> (canonical index symbol, display name)
    "IT": ("NIFTYIT", "NIFTY IT"),
    "BANKING": ("BANKNIFTY", "NIFTY BANK"),
    "FMCG": ("NIFTYFMCG", "NIFTY FMCG"),
    "AUTO": ("NIFTYAUTO", "NIFTY AUTO"),
    "PHARMA": ("NIFTYPHARMA", "NIFTY PHARMA"),
    "METAL": ("NIFTYMETAL", "NIFTY METAL"),
    "ENERGY": ("NIFTYENERGY", "NIFTY ENERGY"),
    "REALTY": ("NIFTYREALTY", "NIFTY REALTY"),
    "FINANCE": ("NIFTYFIN", "NIFTY FIN SERVICE"),
    "CONSUMER": ("NIFTYFMCG", "NIFTY FMCG"),
    "TELECOM": ("NIFTY50", "NIFTY 50"),
    "INFRA": ("NIFTY50", "NIFTY 50"),
    "DIVERSIFIED": ("NIFTY50", "NIFTY 50"),
}

_INDEX_DEFS: list[tuple[str, str, str, str]] = [
    # (canonical, display, sector, yahoo)
    ("NIFTY50", "NIFTY 50", "DIVERSIFIED", "^NSEI"),
    ("SENSEX", "BSE SENSEX", "DIVERSIFIED", "^BSESN"),
    ("BANKNIFTY", "NIFTY BANK", "BANKING", "^NSEBANK"),
    ("NIFTYIT", "NIFTY IT", "IT", "^CNXIT"),
    ("NIFTYFMCG", "NIFTY FMCG", "FMCG", "^CNXFMCG"),
    ("NIFTYAUTO", "NIFTY AUTO", "AUTO", "^CNXAUTO"),
    ("NIFTYPHARMA", "NIFTY PHARMA", "PHARMA", "^CNXPHARMA"),
    ("NIFTYMETAL", "NIFTY METAL", "METAL", "^CNXMETAL"),
    ("NIFTYENERGY", "NIFTY ENERGY", "ENERGY", "^CNXENERGY"),
    ("NIFTYREALTY", "NIFTY REALTY", "REALTY", "^CNXREALTY"),
    ("NIFTYFIN", "NIFTY FIN SERVICE", "FINANCE", "NIFTY_FIN_SERVICE.NS"),
]

INDICES: dict[str, SymbolInfo] = {
    sym: SymbolInfo(sym, name, sector, yahoo, is_index=True) for sym, name, sector, yahoo in _INDEX_DEFS
}


def _s(symbol: str, name: str, sector: str) -> SymbolInfo:
    return SymbolInfo(symbol, name, sector, f"{symbol}.NS")


# A curated NSE large/mid-cap universe. Enough for a credible product without
# shipping a 2000-row exchange dump.
_STOCKS: list[SymbolInfo] = [
    _s("TCS", "Tata Consultancy Services", "IT"),
    _s("INFY", "Infosys", "IT"),
    _s("WIPRO", "Wipro", "IT"),
    _s("HCLTECH", "HCL Technologies", "IT"),
    _s("TECHM", "Tech Mahindra", "IT"),
    _s("LTIM", "LTIMindtree", "IT"),
    _s("RELIANCE", "Reliance Industries", "ENERGY"),
    _s("ONGC", "Oil & Natural Gas Corporation", "ENERGY"),
    _s("BPCL", "Bharat Petroleum", "ENERGY"),
    _s("IOC", "Indian Oil Corporation", "ENERGY"),
    _s("NTPC", "NTPC", "ENERGY"),
    _s("POWERGRID", "Power Grid Corporation", "ENERGY"),
    _s("TATAPOWER", "Tata Power", "ENERGY"),
    _s("HDFCBANK", "HDFC Bank", "BANKING"),
    _s("ICICIBANK", "ICICI Bank", "BANKING"),
    _s("SBIN", "State Bank of India", "BANKING"),
    _s("KOTAKBANK", "Kotak Mahindra Bank", "BANKING"),
    _s("AXISBANK", "Axis Bank", "BANKING"),
    _s("INDUSINDBK", "IndusInd Bank", "BANKING"),
    _s("BANKBARODA", "Bank of Baroda", "BANKING"),
    _s("PNB", "Punjab National Bank", "BANKING"),
    _s("BAJFINANCE", "Bajaj Finance", "FINANCE"),
    _s("BAJAJFINSV", "Bajaj Finserv", "FINANCE"),
    _s("SBILIFE", "SBI Life Insurance", "FINANCE"),
    _s("HDFCLIFE", "HDFC Life Insurance", "FINANCE"),
    _s("SHRIRAMFIN", "Shriram Finance", "FINANCE"),
    _s("HINDUNILVR", "Hindustan Unilever", "FMCG"),
    _s("ITC", "ITC", "FMCG"),
    _s("NESTLEIND", "Nestle India", "FMCG"),
    _s("BRITANNIA", "Britannia Industries", "FMCG"),
    _s("DABUR", "Dabur India", "FMCG"),
    _s("TATACONSUM", "Tata Consumer Products", "FMCG"),
    _s("MARUTI", "Maruti Suzuki India", "AUTO"),
    _s("TATAMOTORS", "Tata Motors", "AUTO"),
    _s("M&M", "Mahindra & Mahindra", "AUTO"),
    _s("BAJAJ-AUTO", "Bajaj Auto", "AUTO"),
    _s("HEROMOTOCO", "Hero MotoCorp", "AUTO"),
    _s("EICHERMOT", "Eicher Motors", "AUTO"),
    _s("TVSMOTOR", "TVS Motor Company", "AUTO"),
    _s("SUNPHARMA", "Sun Pharmaceutical", "PHARMA"),
    _s("DRREDDY", "Dr. Reddy's Laboratories", "PHARMA"),
    _s("CIPLA", "Cipla", "PHARMA"),
    _s("DIVISLAB", "Divi's Laboratories", "PHARMA"),
    _s("APOLLOHOSP", "Apollo Hospitals", "PHARMA"),
    _s("TATASTEEL", "Tata Steel", "METAL"),
    _s("JSWSTEEL", "JSW Steel", "METAL"),
    _s("HINDALCO", "Hindalco Industries", "METAL"),
    _s("VEDL", "Vedanta", "METAL"),
    _s("COALINDIA", "Coal India", "METAL"),
    _s("BHARTIARTL", "Bharti Airtel", "TELECOM"),
    _s("LT", "Larsen & Toubro", "INFRA"),
    _s("ULTRACEMCO", "UltraTech Cement", "INFRA"),
    _s("GRASIM", "Grasim Industries", "INFRA"),
    _s("SHREECEM", "Shree Cement", "INFRA"),
    _s("ADANIENT", "Adani Enterprises", "DIVERSIFIED"),
    _s("ADANIPORTS", "Adani Ports & SEZ", "INFRA"),
    _s("ASIANPAINT", "Asian Paints", "CONSUMER"),
    _s("TITAN", "Titan Company", "CONSUMER"),
    _s("DMART", "Avenue Supermarts", "CONSUMER"),
    _s("TRENT", "Trent", "CONSUMER"),
    _s("ETERNAL", "Eternal (formerly Zomato)", "CONSUMER"),
    _s("NYKAA", "FSN E-Commerce (Nykaa)", "CONSUMER"),
    _s("PAYTM", "One97 Communications (Paytm)", "FINANCE"),
    _s("POLICYBZR", "PB Fintech (Policybazaar)", "FINANCE"),
    _s("DLF", "DLF", "REALTY"),
    _s("GODREJPROP", "Godrej Properties", "REALTY"),
]

REGISTRY: dict[str, SymbolInfo] = {s.symbol: s for s in _STOCKS}
REGISTRY.update(INDICES)


#: Retired tickers that should still resolve for users who know the old name.
ALIASES: dict[str, str] = {"ZOMATO": "ETERNAL"}


def resolve_alias(symbol: str) -> str:
    s = symbol.strip().upper()
    return ALIASES.get(s, s)


def get_symbol_info(symbol: str) -> SymbolInfo | None:
    return REGISTRY.get(resolve_alias(symbol))


def is_known(symbol: str) -> bool:
    return symbol.strip().upper() in REGISTRY


def to_yahoo(symbol: str) -> str:
    """Canonical NSE symbol -> Yahoo ticker, with a sane default for unknowns."""
    info = get_symbol_info(symbol)
    if info:
        return info.yahoo
    s = resolve_alias(symbol)
    return s if s.startswith("^") or "." in s else f"{s}.NS"


def sector_of(symbol: str) -> str | None:
    info = get_symbol_info(symbol)
    return info.sector if info else None


def sector_index_for(symbol: str) -> tuple[str, str] | None:
    """(display name, canonical index symbol) of a symbol's sector index."""
    sector = sector_of(symbol)
    if not sector:
        return None
    pair = SECTOR_INDICES.get(sector)
    if not pair:
        return None
    index_symbol, display = pair
    return display, index_symbol


def display_name(symbol: str) -> str:
    info = get_symbol_info(symbol)
    return info.name if info else symbol.strip().upper()


def search(query: str, *, limit: int = 10) -> list[SymbolInfo]:
    """Rank: exact symbol, symbol prefix, name prefix, then substring."""
    q = query.strip().upper()
    if not q:
        return []
    aliased = ALIASES.get(q)
    if aliased and aliased in REGISTRY:
        return [REGISTRY[aliased]]
    exact, sym_prefix, name_prefix, contains = [], [], [], []
    for info in REGISTRY.values():
        name_u = info.name.upper()
        if info.symbol == q:
            exact.append(info)
        elif info.symbol.startswith(q):
            sym_prefix.append(info)
        elif name_u.startswith(q):
            name_prefix.append(info)
        elif q in info.symbol or q in name_u:
            contains.append(info)
    ranked = exact + sym_prefix + name_prefix + contains
    return ranked[:limit]


def all_symbols(include_indices: bool = False) -> list[str]:
    return [s.symbol for s in REGISTRY.values() if include_indices or not s.is_index]
