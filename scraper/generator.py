import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import re
import datetime
import urllib3
import html
import traceback
from scraper.crawler import normalize_url, crawl_website_with_sitemap

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Try different parsers, with fallback options
def get_soup(html_content):
    """Create BeautifulSoup object with fallback parsers"""
    parsers = ['html.parser', 'lxml', 'html5lib']
    
    for parser in parsers:
        try:
            return BeautifulSoup(html_content, parser)
        except Exception as e:
            print(f"Parser {parser} failed: {str(e)}")
            continue
    
    # If all parsers fail, use the most basic approach
    print("WARNING: All parsers failed. Using minimal approach.")
    return BeautifulSoup(html_content, 'html.parser')

def clean_text(text):
    """Clean up text by removing extra whitespace, HTML, and other artifacts"""
    if not text:
        return ""
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove data attributes and other artifacts
    text = re.sub(r'data-[a-zA-Z0-9_\-]+="[^"]+"', '', text)
    text = re.sub(r'id="[^"]+"', '', text)
    text = re.sub(r'class="[^"]+"', '', text)
    
    # Replace multiple whitespace with single space
    text = re.sub(r'\s+', ' ', text)
    
    # Remove leading/trailing whitespace
    return text.strip()

def normalize_title(title):
    """Normalize title to make it more readable"""
    # Remove common suffixes like " - Website Name"
    title = re.sub(r'\s+[-|]\s+.*$', '', title)
    title = clean_text(title)
    
    # Capitalize first letter of each word for consistency
    title = ' '.join(word.capitalize() if len(word) > 3 or i == 0 
                     else word for i, word in enumerate(title.split()))
    
    return title

def generate_llms_txt_from_sitemap(url, max_pages=50):
    """
    Generate LLMs.txt content using sitemap crawling.
    
    Args:
        url (str): The URL to extract information from
        max_pages (int): Maximum number of pages to process
        
    Returns:
        str: Content for LLMs.txt file in markdown format
    """
    try:
        # Normalize the URL
        url = normalize_url(url)
        
        print(f"Generating LLMs.txt content for {url} using sitemap...")
        
        # Crawl website with sitemap and extract metadata
        site_data = crawl_website_with_sitemap(url, max_pages=max_pages)
        
        # Build the LLMs.txt file
        llms_txt = f"# {site_data['homepage']['title']}\n\n"
        
        # Add homepage description as blockquote if available
        if site_data['homepage']['description']:
            llms_txt += f"**{site_data['homepage']['description']}**\n\n"
        else:
            domain = urlparse(url).netloc
            llms_txt += f"**Website at {domain}**\n\n"
        
        # Add pages from sitemap
        if site_data['pages']:
            llms_txt += "## Pages from Sitemap\n\n"
            
            # Sort pages by URL for consistent output
            sorted_pages = sorted(site_data['pages'], key=lambda x: x['url'])
            
            for page in sorted_pages:
                # Create a clean title
                page_title = page['title']
                page_url = page['url']
                page_desc = page['description']
                
                # Add the page entry
                llms_txt += f"### [{page_title}]({page_url})\n"
                
                # Add description if available
                if page_desc:
                    llms_txt += f"{page_desc}\n\n"
                else:
                    llms_txt += "\n"
        
        return llms_txt
        
    except Exception as e:
        print(f"Error generating LLMs.txt with sitemap: {str(e)}")
        traceback.print_exc()
        # Return a basic file if there's an error
        domain = urlparse(url).netloc
        basic_output = f"""# {domain}
> This website could not be analyzed properly using sitemap.

## Main Website
- [Homepage](https://{domain}): Website homepage
"""
        return basic_output

def clean_urls_in_content(content):
    """
    Final safety check to remove any .md extensions from URLs in content
    
    Args:
        content (str): Content that might contain markdown links with .md extensions
        
    Returns:
        str: Cleaned content with no .md extensions in URLs
    """
    # Pattern to match markdown links with .md extensions
    pattern = r'\[(.*?)\]\((.*?)\.md([^\)]*)\)'
    
    def replace_link(match):
        link_text = match.group(1)
        url = match.group(2)
        extra = match.group(3) if match.group(3) else ""
        
        # Make sure URL has https:// if needed
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        return f'[{link_text}]({url}{extra})'
    
    # Replace all instances
    return re.sub(pattern, replace_link, content)

def generate_llms_txt(url):
    """
    Generate content for LLMs.txt file
    
    Args:
        url (str): The URL to extract information from
        
    Returns:
        str: Content for LLMs.txt file
    """
    # First try the new sitemap-based approach
    try:
        llms_txt_content = generate_llms_txt_from_sitemap(url)
        
        # Apply final safety check
        llms_txt_content = clean_urls_in_content(llms_txt_content)
        
        return llms_txt_content
    except Exception as e:
        print(f"Sitemap approach failed: {str(e)}")
        print("Falling back to traditional method...")
        traceback.print_exc()
    
    # Fall back to the traditional approach if sitemap fails
    try:
        # Normalize the URL
        url = normalize_url(url)
        
        # Send request with appropriate headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        
        if response.status_code != 200:
            domain = urlparse(url).netloc
            error_output = f"""# {domain}
> This website could not be accessed (Status code: {response.status_code})

## Main Website
- [Homepage](https://{domain}): Website homepage
"""
            # Apply cleaning to ensure no .md extensions
            return clean_urls_in_content(error_output)
        
        # Parse the HTML
        soup = get_soup(response.text)
        
        # Extract site information
        site_info = extract_site_info(url, response.text)
        
        # Build the LLMs.txt file according to the spec
        llms_txt = f"# {site_info['title']}\n"
        
        # Add description as blockquote
        if site_info['description']:
            llms_txt += f"> {site_info['description']}\n\n"
        else:
            domain = urlparse(url).netloc
            llms_txt += f"> Website at {domain}\n\n"
        
        # Add general information paragraph
        domain = urlparse(url).netloc
        llms_txt += f"This file provides information about content available on {domain}. "
     
        
        # Add file lists with H2 headers
        if site_info['important_links']:
            # Group links by domain/path to create meaningful sections
            sections = {}
            processed_urls = set()  # For deduplication
            
            for link_text, link_url in site_info['important_links']:
                parsed_url = urlparse(link_url)
                
                # Skip external links
                if parsed_url.netloc != urlparse(url).netloc:
                    continue
                
                # Skip if already processed (deduplication)
                if link_url in processed_urls:
                    continue
                
                processed_urls.add(link_url)
                
                # Determine section based on first path segment
                if not parsed_url.path or parsed_url.path == '/':
                    section = 'Main Pages'
                else:
                    path_segments = [s for s in parsed_url.path.split('/') if s]
                    if path_segments:
                        section = path_segments[0].capitalize()
                    else:
                        section = 'Main Pages'
                
                if section not in sections:
                    sections[section] = []
                
                # Make sure the URL is normalized and has https:// but no .md
                clean_url = normalize_url(link_url)
                
                # Normalize link text
                if not link_text or link_text.lower() in ['click here', 'read more', 'learn more']:
                    # Generate a better title
                    if parsed_url.path == '/' or not parsed_url.path:
                        link_text = 'Homepage'
                    else:
                        link_text = parsed_url.path.split('/')[-1].replace('-', ' ').replace('_', ' ').capitalize()
                
                sections[section].append((link_text, clean_url))
            
            # If we don't have good sections, use default ones
            if not sections:
                domain = urlparse(url).netloc
                sections['Main Pages'] = [('Homepage', f"https://{domain}")]
            
            # Add each section to the LLMs.txt
            for section, links in sections.items():
                llms_txt += f"## {section}\n"
                for link_text, clean_url in links:
                    llms_txt += f"- [{link_text}]({clean_url})\n"
                llms_txt += "\n"
            
        else:
            # If no links found, just include the homepage
            domain = urlparse(url).netloc
            llms_txt += "## Main Website\n"
            llms_txt += f"- [Homepage](https://{domain}): Website homepage\n\n"
        
        # One final check to ensure no .md extensions remain
        llms_txt = clean_urls_in_content(llms_txt)
        
        return llms_txt
        
    except Exception as e:
        print(f"Error generating LLMs.txt: {str(e)}")
        traceback.print_exc()
        # Return a basic file if there's an error
        domain = urlparse(url).netloc
        basic_output = f"""# {domain}
> This website could not be analyzed properly

## Main Website
- [Homepage](https://{domain}): Website homepage
"""
        # Apply cleaning to ensure no .md extensions
        return clean_urls_in_content(basic_output)

def extract_site_info(url, html_content):
    """Extract site information for LLMs.txt"""
    # Normalize the URL
    url = normalize_url(url)
    
    soup = get_soup(html_content)
    
    # Extract title
    title = urlparse(url).netloc  # Default to domain name
    if soup.title:
        title = normalize_title(soup.title.string)
    else:
        h1 = soup.find('h1')
        if h1:
            title = normalize_title(h1.get_text())
    
    # Try to extract description
    description = ""
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        description = clean_text(meta_desc.get('content'))
    
    # If no description, try other meta tags
    if not description:
        og_desc = soup.find('meta', attrs={'property': 'og:description'})
        if og_desc and og_desc.get('content'):
            description = clean_text(og_desc.get('content'))
    
    # If still no description, try to get the first paragraph
    if not description:
        first_p = soup.find('p')
        if first_p:
            description = clean_text(first_p.get_text())
    
    # Find important links
    important_links = []
    processed_urls = set()  # Track processed URLs to avoid duplicates
    
    # Look for navigation menus first
    nav_elements = soup.select('nav, .nav, .menu, .navigation, .navbar, header')
    for nav in nav_elements:
        for link in nav.find_all('a', href=True):
            href = link['href']
            text = clean_text(link.get_text())
            
            if text and href and not href.startswith('#') and not href.startswith('javascript:'):
                # Make absolute URL if relative
                if not href.startswith(('http://', 'https://')):
                    href = urljoin(url, href)
                
                # Skip if already processed or external
                parsed_href = urlparse(href)
                if href in processed_urls or parsed_href.netloc != urlparse(url).netloc:
                    continue
                
                processed_urls.add(href)
                important_links.append((text, href))
    
    # If not enough nav links, get other prominent links
    if len(important_links) < 5:
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = clean_text(a.get_text())
            
            if text and href and not href.startswith('#') and not href.startswith('javascript:'):
                # Make absolute URL if relative
                if not href.startswith(('http://', 'https://')):
                    href = urljoin(url, href)
                
                # Skip if already processed or external
                parsed_href = urlparse(href)
                if href in processed_urls or parsed_href.netloc != urlparse(url).netloc:
                    continue
                
                processed_urls.add(href)
                important_links.append((text, href))
                
                if len(important_links) >= 10:  # Limit to 10 important links
                    break
    
    return {
        'title': title,
        'description': description,
        'important_links': important_links
    }