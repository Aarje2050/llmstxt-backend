from flask import Flask, request, jsonify
from flask_cors import CORS
from scraper.crawler import crawl_website
from scraper.generator import generate_llms_txt, generate_md_files, remove_md_extensions
import os
import json
import traceback
import re

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})  # Enable CORS for all routes

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

@app.route('/api/scrape', methods=['POST'])
def scrape():
    data = request.json
    urls = data.get('urls', [])
    bulk_mode = data.get('bulkMode', False)  # Get bulk mode flag from request
    
    if not urls:
        return jsonify({"error": "No URLs provided"}), 400
    
    result = {}
    for url in urls:
        try:
            print(f"Processing URL: {url}")
            
            # Clean the URL (ensure it has a scheme)
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            # Only crawl if bulk mode is enabled, otherwise just use the single URL
            if bulk_mode:
                print("Bulk mode enabled - crawling website for all URLs")
                discovered_urls = crawl_website(url)
            else:
                print("Single URL mode - skipping crawl")
                discovered_urls = [url]  # Just use the single URL provided
            
            print(f"Working with {len(discovered_urls)} URLs")
            
            # Generate LLMs.txt content
            llms_txt_content = generate_llms_txt(url)
            
            # Apply one final safety check to ensure there are no .md extensions
            llms_txt_content = clean_urls_in_content(llms_txt_content)
            
            # Generate markdown files for each URL
            md_files = generate_md_files(url, discovered_urls)
            
            result[url] = {
                'status': 'success',
                'llms_txt': llms_txt_content,
                'md_files': md_files,
                'discovered_urls': discovered_urls
            }
        except Exception as e:
            print(f"Error processing {url}: {str(e)}")
            print(traceback.format_exc())
            result[url] = {
                'status': 'error',
                'error': str(e)
            }
    
    return jsonify(result)

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"})

@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"message": "API is working properly!"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)