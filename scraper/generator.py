import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
import re
import datetime
import urllib3
import html
import traceback

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

def url_to_md_path(url):
    """Convert URL to markdown path with domain included"""
    parsed = urlparse(url)
    domain = parsed.netloc
    path = parsed.path
    
    # Handle root URL
    if not path or path == '/':
        return f"{domain}/index.md"
    
    # Remove trailing slash
    if path.endswith('/'):
        path = path[:-1]
    
    # Clean the path (remove special characters)
    clean_path = re.sub(r'[^a-zA-Z0-9/\-_]', '', path)
    
    # Replace slashes with proper directory structure
    md_path = clean_path.replace('/', '/')
    
    # Return with domain and .md extension
    return f"{domain}{md_path}.md"

def extract_site_info(url, html_content):
    """Extract site information for LLMs.txt"""
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

def strip_html_attributes(html_string):
    """Strip HTML attributes that might cause problems in markdown conversion"""
    # Pattern to match HTML tags with attributes
    pattern = r'<([a-z][a-z0-9]*)\s+[^>]*?(/?)>'
    
    # Replace with clean tags (no attributes)
    clean_html = re.sub(pattern, r'<\1\2>', html_string)
    
    return clean_html

def html_to_markdown(element, base_url='', level=0):
    """Convert HTML element to markdown recursively"""
    if element is None:
        return ""
    
    # If the element is a string, return it cleaned
    if isinstance(element, str):
        return clean_text(element)
    
    # Skip script, style, and hidden elements
    tag_name = element.name if hasattr(element, 'name') else None
    if not tag_name or tag_name in ['script', 'style', 'meta', 'link', 'iframe', 'noscript']:
        return ""
    
    # Check if element is hidden
    style = element.get('style', '')
    if 'display:none' in style or 'visibility:hidden' in style:
        return ""
    
    result = ""
    
    # Handle heading tags
    if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        level_num = int(tag_name[1])
        text = clean_text(element.get_text())
        if text:
            result += '#' * level_num + ' ' + text + '\n\n'
    
    # Handle paragraph
    elif tag_name == 'p':
        text = clean_text(element.get_text())
        if text:
            result += text + '\n\n'
    
    # Handle links
    elif tag_name == 'a' and element.get('href'):
        href = element.get('href')
        text = clean_text(element.get_text())
        
        if text and href and not href.startswith('javascript:'):
            # Make absolute URL if relative
            if not href.startswith(('http://', 'https://')):
                href = urljoin(base_url, href)
            
            result += f"[{text}]({href})"
        else:
            # Process children normally if not a valid link
            for child in element.children:
                result += html_to_markdown(child, base_url, level)
    
    # Handle images
    elif tag_name == 'img' and element.get('src'):
        src = element.get('src')
        alt = element.get('alt', '')
        
        # Make absolute URL if relative
        if not src.startswith(('http://', 'https://')):
            src = urljoin(base_url, src)
        
        result += f"![{alt}]({src})\n\n"
    
    # Handle lists
    elif tag_name == 'ul':
        for li in element.find_all('li', recursive=False):
            li_text = clean_text(li.get_text())
            if li_text:
                result += '- ' + li_text + '\n'
        result += '\n'
    
    elif tag_name == 'ol':
        for i, li in enumerate(element.find_all('li', recursive=False)):
            li_text = clean_text(li.get_text())
            if li_text:
                result += f"{i+1}. " + li_text + '\n'
        result += '\n'
    
    # Handle blockquotes
    elif tag_name == 'blockquote':
        text = clean_text(element.get_text())
        if text:
            lines = text.split('\n')
            for line in lines:
                if line.strip():
                    result += '> ' + line + '\n'
            result += '\n'
    
    # Handle code
    elif tag_name == 'code':
        text = clean_text(element.get_text())
        if text:
            result += f"`{text}`"
    
    # Handle pre (code blocks)
    elif tag_name == 'pre':
        text = clean_text(element.get_text())
        if text:
            result += f"```\n{text}\n```\n\n"
    
    # Handle tables
    elif tag_name == 'table':
        rows = element.find_all('tr')
        if rows:
            # Extract headers
            headers = []
            header_row = None
            
            # Look for headers in thead
            thead = element.find('thead')
            if thead:
                header_row = thead.find('tr')
            
            # If no thead, use first row as header
            if not header_row and rows:
                header_row = rows[0]
            
            if header_row:
                headers = [clean_text(th.get_text()) for th in header_row.find_all(['th', 'td'])]
                if all(headers):  # Only use if all headers have content
                    # Add header row
                    result += '| ' + ' | '.join(headers) + ' |\n'
                    # Add separator row
                    result += '| ' + ' | '.join(['---'] * len(headers)) + ' |\n'
                    
                    # Add data rows (skip header row if we're using it as a header)
                    start_idx = 1 if header_row == rows[0] else 0
                    for row in rows[start_idx:]:
                        cells = [clean_text(td.get_text()) for td in row.find_all(['td', 'th'])]
                        if cells:
                            # Ensure right number of cells
                            while len(cells) < len(headers):
                                cells.append('')
                            cells = cells[:len(headers)]  # Truncate if too many
                            
                            result += '| ' + ' | '.join(cells) + ' |\n'
                    
                    result += '\n'
    
    # Handle divs and other container elements
    elif tag_name in ['div', 'section', 'article', 'main', 'header', 'footer', 'nav', 'aside']:
        # Process all children
        for child in element.children:
            result += html_to_markdown(child, base_url, level)
    
    # For all other elements, just process children
    else:
        for child in element.children:
            result += html_to_markdown(child, base_url, level)
    
    return result

def generate_llms_txt(url):
    """
    Generate content for LLMs.txt file with comprehensive markdown conversion
    
    Args:
        url (str): The URL to extract information from
        
    Returns:
        str: Content for LLMs.txt file
    """
    try:
        # Send request with appropriate headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        
        if response.status_code != 200:
            domain = urlparse(url).netloc
            return f"""# {domain}
> This website could not be accessed (Status code: {response.status_code})

## Main Website
- [Homepage]({domain}/index.md): Website homepage
"""
        
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
        llms_txt += f"The links below can be used to access detailed content from the website. "
        llms_txt += f"All content linked is available for training AI/ML models unless otherwise noted.\n\n"
        
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
                
                # Convert link URL to md file path with domain
                md_path = url_to_md_path(link_url)
                
                # Normalize link text
                if not link_text or link_text.lower() in ['click here', 'read more', 'learn more']:
                    # Generate a better title
                    if parsed_url.path == '/' or not parsed_url.path:
                        link_text = 'Homepage'
                    else:
                        link_text = parsed_url.path.split('/')[-1].replace('-', ' ').replace('_', ' ').capitalize()
                
                sections[section].append((link_text, md_path))
            
            # If we don't have good sections, use default ones
            if not sections:
                domain = urlparse(url).netloc
                sections['Main Pages'] = [('Homepage', f"{domain}/index.md")]
            
            # Add each section to the LLMs.txt
            for section, links in sections.items():
                llms_txt += f"## {section}\n"
                for link_text, md_path in links:
                    llms_txt += f"- [{link_text}]({md_path})\n"
                llms_txt += "\n"
            
        else:
            # If no links found, just include the homepage
            domain = urlparse(url).netloc
            llms_txt += "## Main Website\n"
            llms_txt += f"- [Homepage]({domain}/index.md): Website homepage\n\n"
        
        return llms_txt
        
    except Exception as e:
        print(f"Error generating LLMs.txt: {str(e)}")
        traceback.print_exc()
        # Return a basic file if there's an error
        domain = urlparse(url).netloc
        return f"""# {domain}
> This website could not be analyzed properly

## Main Website
- [Homepage]({domain}/index.md): Website homepage
"""

def convert_full_html_to_markdown(html_content, base_url):
    """Convert full HTML content to clean markdown"""
    try:
        # Parse the HTML
        soup = get_soup(html_content)
        
        # Remove unwanted elements
        for tag in soup.find_all(['script', 'style', 'iframe', 'noscript']):
            tag.decompose()
        
        # Extract title
        title = "Website Content"
        if soup.title:
            title = normalize_title(soup.title.string)
        
        # Start building markdown
        markdown = f"# {title}\n\n"
        
        # Add URL reference
        markdown += f"Source: {base_url}\n\n"
        
        # Convert the entire body to markdown
        body_markdown = html_to_markdown(soup.body, base_url)
        
        # Clean up the markdown
        # Remove excess whitespace
        body_markdown = re.sub(r'\n{3,}', '\n\n', body_markdown)
        # Remove any HTML-like artifacts
        body_markdown = re.sub(r'<[^>]+>', '', body_markdown)
        
        markdown += body_markdown
        
        return markdown
    
    except Exception as e:
        print(f"Error converting HTML to markdown: {str(e)}")
        traceback.print_exc()
        return f"# Error Processing Content\n\nThere was an error converting content to markdown:\n\n{str(e)}"

def generate_md_files(base_url, urls):
    """
    Generate markdown files for each URL with proper conversion from HTML to Markdown
    
    Args:
        base_url (str): The base URL of the website
        urls (list): List of URLs to generate markdown for
        
    Returns:
        dict: Dictionary with URL as key and markdown content as value
    """
    md_files = {}
    
    for url in urls:
        try:
            print(f"Generating markdown for: {url}")
            
            # Send request with appropriate headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            
            if response.status_code == 200:
                # Create a clean title for the filename
                path = urlparse(url).path
                clean_title = path.replace('/', '-').strip('-')
                if not clean_title:
                    clean_title = 'index'
                
                # Convert HTML to clean markdown
                md_content = convert_full_html_to_markdown(response.text, url)
                
                # Add to the dictionary
                md_files[url] = {
                    'filename': f"{clean_title}.md",
                    'content': md_content
                }
            else:
                print(f"Failed to fetch {url}, status code: {response.status_code}")
                clean_title = urlparse(url).path.replace('/', '-').strip('-') or 'index'
                md_files[url] = {
                    'filename': f"error-{clean_title}.md",
                    'content': f"# Error\n\nFailed to access {url}: Status code {response.status_code}"
                }
                
        except Exception as e:
            print(f"Error generating markdown for {url}: {str(e)}")
            traceback.print_exc()
            clean_title = urlparse(url).path.replace('/', '-').strip('-') or 'index'
            md_files[url] = {
                'filename': f"error-{clean_title}.md",
                'content': f"# Error\n\nFailed to process {url}: {str(e)}"
            }
    
    return md_files