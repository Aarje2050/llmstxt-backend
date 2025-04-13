import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Try different parsers, with fallback options
def get_soup(html_content):
    """Create BeautifulSoup object with fallback parsers"""
    parsers = ['lxml', 'html.parser', 'html5lib']
    
    for parser in parsers:
        try:
            return BeautifulSoup(html_content, parser)
        except Exception as e:
            print(f"Parser {parser} failed: {str(e)}")
            continue
    
    # If all parsers fail, use the most basic one with a clear warning
    print("WARNING: All parsers failed. Using minimal parser - results may be limited.")
    return BeautifulSoup(html_content, 'html.parser')

def normalize_url(url):
    """Normalize URL to handle various patterns and ensure no .md extensions"""
    # Skip if empty
    if not url:
        return url
        
    # Remove .md extension if present
    if url.endswith('.md'):
        url = url[:-3]
    
    # Make sure URL has a scheme
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Parse the URL
    parsed = urlparse(url)
    
    # Build normalized URL
    normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    
    # Remove trailing slash for consistency, unless it's the root path
    if normalized_url.endswith('/') and normalized_url != f"{parsed.scheme}://{parsed.netloc}/":
        normalized_url = normalized_url[:-1]
    
    # Remove .md extension if it somehow got into the path
    if normalized_url.endswith('.md'):
        normalized_url = normalized_url[:-3]
    
    # Keep query parameters if they exist
    if parsed.query:
        normalized_url += f"?{parsed.query}"
    
    return normalized_url

def crawl_website(base_url, max_pages=50):
    """
    Crawl a website and extract all URLs within the same domain.
    
    Args:
        base_url (str): The starting URL to crawl
        max_pages (int): Maximum number of pages to crawl
        
    Returns:
        list: List of discovered URLs
    """
    print(f"Starting to crawl: {base_url}")
    
    # Normalize the base URL
    base_url = normalize_url(base_url)
    
    # Parse the base URL to get the domain
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc
    
    # Initialize sets for tracking
    visited_urls = set()
    urls_to_visit = {base_url}
    discovered_urls = set()
    
    # Continue until no more URLs to visit or max limit reached
    while urls_to_visit and len(visited_urls) < max_pages:
        # Get the next URL to visit
        current_url = urls_to_visit.pop()
        
        # Skip if already visited
        if current_url in visited_urls:
            continue
        
        try:
            print(f"Crawling: {current_url}")
            
            # Add a small delay to be respectful
            time.sleep(0.3)
            
            # Send request with appropriate headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            
            # Disable SSL verification to avoid certificate issues
            response = requests.get(current_url, headers=headers, timeout=15, verify=False)
            
            # Process only if status code is OK
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '').lower()
                
                # Only process HTML content
                if 'text/html' in content_type:
                    visited_urls.add(current_url)
                    discovered_urls.add(current_url)
                    
                    # Parse the HTML content with fallback parsers
                    soup = get_soup(response.text)
                    
                    # Extract all links
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        
                        # Skip empty, javascript, and anchor links
                        if not href or href.startswith('javascript:') or href == '#':
                            continue
                            
                        # Join relative URLs
                        full_url = urljoin(current_url, href)
                        
                        # Normalize the URL to remove .md extensions
                        full_url = normalize_url(full_url)
                        
                        parsed_url = urlparse(full_url)
                        
                        # Filter URLs:
                        # 1. Same domain
                        # 2. HTTP/HTTPS scheme
                        if (parsed_url.netloc == base_domain and
                            parsed_url.scheme in ('http', 'https')):
                            
                            # Clean the URL (remove fragments and query params for deduplication)
                            clean_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
                            
                            # Add trailing slash if needed for consistency
                            if not clean_url.endswith('/') and '.' not in clean_url.split('/')[-1]:
                                clean_url += '/'
                            
                            # Remove common file extensions we don't want
                            if not any(clean_url.endswith(ext) for ext in 
                                      ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.js', '.css']):
                                
                                # Remove .md extension if present
                                if clean_url.endswith('.md'):
                                    clean_url = clean_url[:-3]
                                
                                # Add to the queue if not visited
                                if clean_url not in visited_urls and clean_url not in urls_to_visit:
                                    urls_to_visit.add(clean_url)
                else:
                    print(f"Skipping non-HTML content: {current_url}")
            else:
                print(f"Failed to fetch {current_url}, status code: {response.status_code}")
                
        except Exception as e:
            print(f"Error crawling {current_url}: {str(e)}")
            continue
    
    print(f"Crawling complete. Discovered {len(discovered_urls)} URLs.")
    
    # If no URLs were discovered, at least include the base URL
    if not discovered_urls:
        discovered_urls.add(base_url)
    
    # Final cleanup: ensure all URLs are normalized and don't have .md extensions
    clean_discovered_urls = [normalize_url(url) for url in discovered_urls]
        
    return clean_discovered_urls