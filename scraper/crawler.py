import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
import urllib3
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def extract_page_metadata(url):
    """
    Extract title and meta description from a webpage
    
    Args:
        url (str): URL to extract metadata from
        
    Returns:
        dict: Dictionary with title and description
    """
    try:
        # Send request with appropriate headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        # Disable SSL verification to avoid certificate issues
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        
        if response.status_code != 200:
            return {
                'title': f"Failed to fetch page (Status: {response.status_code})",
                'description': "Could not retrieve page metadata"
            }
        
        # Parse HTML content
        soup = get_soup(response.text)
        
        # Extract title
        title = "Unnamed Page"
        if soup.title:
            title = soup.title.string.strip() if soup.title.string else "Unnamed Page"
        
        # Extract meta description
        description = ""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            description = meta_desc.get('content').strip()
        
        # If no meta description, try OG description
        if not description:
            og_desc = soup.find('meta', attrs={'property': 'og:description'})
            if og_desc and og_desc.get('content'):
                description = og_desc.get('content').strip()
        
        # If still no description, try to get the first paragraph
        if not description:
            first_p = soup.find('p')
            if first_p and first_p.get_text():
                description = first_p.get_text().strip()
                
                # Limit description to a reasonable length
                if len(description) > 250:
                    description = description[:250] + "..."
        
        return {
            'title': title,
            'description': description
        }
    
    except Exception as e:
        print(f"Error extracting metadata from {url}: {str(e)}")
        return {
            'title': "Error fetching page",
            'description': f"An error occurred: {str(e)}"
        }

def parse_sitemap(sitemap_url):
    """
    Parse XML sitemap and extract URLs
    
    Args:
        sitemap_url (str): URL of the sitemap
        
    Returns:
        list: List of URLs found in the sitemap
    """
    urls = []
    try:
        # Send request with appropriate headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        print(f"Fetching sitemap: {sitemap_url}")
        response = requests.get(sitemap_url, headers=headers, timeout=15, verify=False)
        
        if response.status_code != 200:
            print(f"Failed to fetch sitemap. Status code: {response.status_code}")
            return urls
        
        content_type = response.headers.get('Content-Type', '').lower()
        
        # Check if it's a XML sitemap
        if 'application/xml' in content_type or 'text/xml' in content_type or '<urlset' in response.text:
            # Handle regular XML sitemap
            root = ET.fromstring(response.text)
            
            # Extract URLs from urlset (standard sitemap)
            if 'urlset' in root.tag:
                for url_element in root.findall('.//{*}url'):
                    loc_element = url_element.find('.//{*}loc')
                    if loc_element is not None and loc_element.text:
                        urls.append(normalize_url(loc_element.text))
            
            # Handle sitemap index files
            elif 'sitemapindex' in root.tag:
                for sitemap_element in root.findall('.//{*}sitemap'):
                    loc_element = sitemap_element.find('.//{*}loc')
                    if loc_element is not None and loc_element.text:
                        # Recursively fetch and parse child sitemaps
                        child_urls = parse_sitemap(loc_element.text)
                        urls.extend(child_urls)
        
        # If it's not a valid XML sitemap, try to find links in HTML
        elif 'text/html' in content_type:
            soup = get_soup(response.text)
            
            # Look for links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href and not href.startswith('#') and not href.startswith('javascript:'):
                    full_url = urljoin(sitemap_url, href)
                    urls.append(normalize_url(full_url))
        
        print(f"Found {len(urls)} URLs in sitemap")
        return urls
    
    except ET.ParseError as e:
        print(f"XML parsing error in sitemap {sitemap_url}: {str(e)}")
        # Try a more forgiving approach by extracting URLs with regex
        try:
            url_pattern = re.compile(r'<loc>(.*?)</loc>')
            matches = url_pattern.findall(response.text)
            for match in matches:
                urls.append(normalize_url(match))
            print(f"Extracted {len(urls)} URLs using regex fallback")
            return urls
        except Exception as e2:
            print(f"Failed to parse sitemap with regex: {str(e2)}")
            return urls
    
    except Exception as e:
        print(f"Error parsing sitemap {sitemap_url}: {str(e)}")
        return urls

def crawl_website_with_sitemap(base_url, max_pages=50, use_sitemap=True):
    """
    Crawl a website using sitemap.xml if available, and extract metadata from each page.
    Falls back to traditional crawling if sitemap is not available.
    
    Args:
        base_url (str): The starting URL to crawl
        max_pages (int): Maximum number of pages to crawl
        use_sitemap (bool): Whether to attempt to use sitemap
        
    Returns:
        dict: Dictionary with discovered URLs and their metadata
    """
    print(f"Starting to crawl: {base_url}")
    
    # Normalize the base URL
    base_url = normalize_url(base_url)
    
    # Parse the base URL to get the domain
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc
    
    # Get homepage metadata first
    print("Fetching homepage metadata...")
    homepage_metadata = extract_page_metadata(base_url)
    
    # Initialize data structures
    discovered_urls = []
    site_metadata = {
        'homepage': {
            'url': base_url,
            'title': homepage_metadata['title'],
            'description': homepage_metadata['description']
        },
        'pages': []
    }
    
    # Try sitemap first if enabled
    if use_sitemap:
        # Check common sitemap locations
        sitemap_locations = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap-index.xml",
            f"{base_url}/wp-sitemap.xml",  # WordPress
            f"{base_url}/sitemap.php",     # Some CMS systems
            f"{base_url}/sitemap"          # Generic fallback
        ]
        
        sitemap_urls = []
        
        # Try each possible sitemap location
        for sitemap_url in sitemap_locations:
            print(f"Checking for sitemap at: {sitemap_url}")
            try:
                response = requests.head(sitemap_url, timeout=10, verify=False)
                if response.status_code == 200:
                    sitemap_urls = parse_sitemap(sitemap_url)
                    if sitemap_urls:
                        print(f"Found valid sitemap at {sitemap_url} with {len(sitemap_urls)} URLs")
                        break
            except Exception as e:
                print(f"Failed to check sitemap at {sitemap_url}: {str(e)}")
        
        # If we found a sitemap and it has URLs, use those
        if sitemap_urls:
            # Filter to keep only URLs from the same domain and limit to max_pages
            sitemap_urls = [url for url in sitemap_urls if urlparse(url).netloc == base_domain][:max_pages]
            discovered_urls = sitemap_urls
            
            print(f"Found {len(discovered_urls)} URLs from sitemap on the same domain")
    
    # If no sitemap found or disabled, fall back to traditional crawling
    if not discovered_urls:
        print("No sitemap found or sitemap disabled. Falling back to traditional crawling.")
        discovered_urls = crawl_website(base_url, max_pages)
    
    # Process each discovered URL to extract metadata
    print(f"Processing {len(discovered_urls)} discovered URLs...")
    
    # Use ThreadPoolExecutor to process URLs in parallel for better performance
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit tasks
        future_to_url = {executor.submit(extract_page_metadata, url): url for url in discovered_urls}
        
        # Process results as they complete
        completed = 0
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                metadata = future.result()
                site_metadata['pages'].append({
                    'url': url,
                    'title': metadata['title'],
                    'description': metadata['description']
                })
                
                completed += 1
                if completed % 5 == 0 or completed == len(discovered_urls):
                    print(f"Processed {completed}/{len(discovered_urls)} URLs...")
                
            except Exception as e:
                print(f"Error processing {url}: {str(e)}")
    
    print(f"Crawling complete. Processed {len(site_metadata['pages'])} pages.")
    return site_metadata

# Original crawl function - keep for compatibility with existing code
def crawl_website(base_url, max_pages=50):
    """
    Crawl a website and extract all URLs within the same domain.
    
    Args:
        base_url (str): The starting URL to crawl
        max_pages (int): Maximum number of pages to crawl
        
    Returns:
        list: List of discovered URLs
    """
    print(f"Starting traditional crawl: {base_url}")
    
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
    
    print(f"Traditional crawling complete. Discovered {len(discovered_urls)} URLs.")
    
    # If no URLs were discovered, at least include the base URL
    if not discovered_urls:
        discovered_urls.add(base_url)
    
    # Final cleanup: ensure all URLs are normalized and don't have .md extensions
    clean_discovered_urls = [normalize_url(url) for url in discovered_urls]
        
    return clean_discovered_urls