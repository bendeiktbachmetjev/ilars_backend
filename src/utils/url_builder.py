"""
Database URL utilities
"""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from typing import Optional


def build_async_url(sync_url: str) -> str:
    """
    Convert postgres:// to postgresql+asyncpg:// and remove sslmode from URL
    
    Args:
        sync_url: Original database URL
        
    Returns:
        Async-compatible database URL
    """
    if not sync_url:
        return sync_url
    
    parts = urlsplit(sync_url)
    scheme = parts.scheme
    
    if "+" in scheme:
        base_scheme = scheme.split("+")[0]
    else:
        base_scheme = scheme
    
    if base_scheme.startswith("postgres"):
        # Remove sslmode from query parameters (asyncpg doesn't support it in URL)
        query_pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
        query_pairs.pop("sslmode", None)
        new_query = urlencode(query_pairs) if query_pairs else ""
        
        new_scheme = "postgresql+asyncpg"
        new_parts = (new_scheme, parts.netloc, parts.path, new_query, parts.fragment)
        return urlunsplit(new_parts)
    
    return sync_url


def normalize_database_url(database_url: str) -> str:
    """
    Normalize database URL for connection pooling
    
    Args:
        database_url: Original database URL
        
    Returns:
        Normalized database URL
    """
    if not database_url:
        return database_url
    
    # Switch from Transaction Pooler (6543) to Session Pooler (5432)
    # Transaction Pooler doesn't support prepared statements
    if ":6543" in database_url:
        database_url = database_url.replace(":6543", ":5432")
        print("Switched from Transaction Pooler (6543) to Session Pooler (5432) for prepared statements support")
    elif ".pooler.supabase.com" in database_url and ":5432" not in database_url:
        # If pooler but port not explicitly specified - add 5432
        database_url = database_url.replace(".pooler.supabase.com", ".pooler.supabase.com:5432")
        print("Added Session Pooler port (5432) for prepared statements support")
    
    return database_url

