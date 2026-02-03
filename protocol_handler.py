"""
Protocol Handler for scanlink:// URLs

Parses custom protocol URLs triggered from browser links like:
    <a href="scanlink://scan?docId=123&callback=https://example.com/upload">Scan</a>

URL Format:
    scanlink://action?param1=value1&param2=value2

Supported Actions:
    - scan: Start a scan job
        - docId: Optional document ID to associate with the scan
        - callback: Optional URL to POST the result to

Examples:
    scanlink://scan
    scanlink://scan?docId=123
    scanlink://scan?docId=123&callback=https://myapp.com/api/upload
"""

from urllib.parse import urlparse, parse_qs
from utils import get_logger

logger = get_logger()

PROTOCOL_SCHEME = 'scanlink'

def parse_protocol_url(url):
    """
    Parse a scanlink:// URL and return a structured command object.
    
    Args:
        url: The full URL string (e.g., 'scanlink://scan?docId=123')
        
    Returns:
        dict: {
            'action': str,      # The action to perform (e.g., 'scan')
            'doc_id': str,      # Optional document ID
            'callback_url': str # Optional callback URL
        }
        or None if the URL is invalid
    """
    if not url:
        return None
        
    try:
        parsed = urlparse(url)
        
        # Validate scheme
        if parsed.scheme.lower() != PROTOCOL_SCHEME:
            logger.warning(f"Invalid protocol scheme: {parsed.scheme}")
            return None
        
        # Action is the netloc (host part)
        action = parsed.netloc.lower() if parsed.netloc else 'scan'
        
        # Parse query parameters
        params = parse_qs(parsed.query)
        
        # Extract known parameters (take first value if multiple)
        doc_id = params.get('docId', params.get('doc_id', [None]))[0]
        callback_url = params.get('callback', params.get('callback_url', [None]))[0]
        
        result = {
            'action': action,
            'doc_id': doc_id,
            'callback_url': callback_url
        }
        
        logger.info(f"Parsed protocol URL: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to parse protocol URL '{url}': {e}")
        return None


def is_protocol_url(arg):
    """Check if a command-line argument is a scanlink:// URL."""
    if not arg:
        return False
    return arg.lower().startswith(f'{PROTOCOL_SCHEME}://')


def extract_protocol_url_from_args(args):
    """
    Extract the first scanlink:// URL from command-line arguments.
    
    Args:
        args: List of command-line arguments (e.g., sys.argv)
        
    Returns:
        str: The protocol URL, or None if not found
    """
    for arg in args:
        if is_protocol_url(arg):
            return arg
    return None
