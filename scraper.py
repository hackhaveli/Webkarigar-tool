import csv
import re
import concurrent.futures
import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import urljoin, urlparse
import logging
from tqdm import tqdm
import time
import random
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)

class WebsiteScraper:
    def __init__(self, csv_path, max_workers=5, timeout=30):
        self.csv_path = csv_path
        self.max_workers = max_workers
        self.timeout = timeout
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
        }
        
        # Configure session with retries
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def load_urls(self):
        """Load URLs from CSV file"""
        try:
            df = pd.read_csv(self.csv_path)
            if 'url' not in df.columns:
                raise ValueError("CSV file must contain a 'url' column")
                
            # Clean URLs by removing any trailing spaces
            df['url'] = df['url'].apply(lambda x: x.strip() if isinstance(x, str) else x)
            
            # Ensure URLs have http/https prefix
            df['url'] = df['url'].apply(self.normalize_url)
            
            # Initialize columns if they don't exist
            for col in ['email', 'logo', 'business_name', 'services', 'error']:
                if col not in df.columns:
                    df[col] = None
                    
            return df
        except Exception as e:
            logging.error(f"Error loading CSV: {e}")
            return None
    
    def normalize_url(self, url):
        """Ensure URL has proper http/https prefix"""
        if not url.startswith(('http://', 'https://')):
            return 'https://' + url
        return url
    
    def save_results(self, df):
        """Save results back to CSV"""
        try:
            df.to_csv(self.csv_path, index=False)
            logging.info(f"Results saved to {self.csv_path}")
        except Exception as e:
            logging.error(f"Error saving results: {e}")
    
    def extract_email(self, soup, text, url):
        """Extract email addresses from HTML"""
        emails_found = []
        
        # Method 1: Look for mailto links
        email_links = soup.select('a[href^="mailto:"]')
        if email_links:
            for link in email_links:
                href = link.get('href')
                if href:
                    email = href.replace('mailto:', '').split('?')[0].strip()
                    if email and '@' in email and '.' in email.split('@')[1]:
                        emails_found.append(email)
        
        # Method 2: Use regex to find emails in the HTML
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        regex_emails = re.findall(email_pattern, text)
        if regex_emails:
            # Filter out common false positives
            filtered_emails = [
                email for email in regex_emails 
                if not email.endswith(('.png', '.jpg', '.gif', '.svg')) 
                and not email.startswith(('http://', 'https://'))
                and not any(x in email for x in ['%', '&', '=', ';'])
            ]
            emails_found.extend(filtered_emails)
        
        # Method 3: Check for contact pages and scrape them
        if not emails_found:
            contact_links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                link_text = a.text.lower()
                if any(keyword in link_text for keyword in ['contact', 'kontakt', 'impressum']):
                    contact_links.append(href)
            
            if contact_links:
                contact_url = urljoin(url, contact_links[0])
                try:
                    response = self.session.get(
                        contact_url, 
                        headers=self.headers, 
                        timeout=self.timeout
                    )
                    if response.status_code == 200:
                        contact_soup = BeautifulSoup(response.text, 'html.parser')
                        
                        # Look for emails on contact page
                        contact_email_links = contact_soup.select('a[href^="mailto:"]')
                        if contact_email_links:
                            for link in contact_email_links:
                                href = link.get('href')
                                if href:
                                    email = href.replace('mailto:', '').split('?')[0].strip()
                                    if email and '@' in email and '.' in email.split('@')[1]:
                                        emails_found.append(email)
                        
                        # Regex search on contact page
                        contact_emails = re.findall(email_pattern, response.text)
                        filtered_contact_emails = [
                            email for email in contact_emails 
                            if not email.endswith(('.png', '.jpg', '.gif', '.svg'))
                            and not email.startswith(('http://', 'https://'))
                            and not any(x in email for x in ['%', '&', '=', ';'])
                        ]
                        emails_found.extend(filtered_contact_emails)
                except Exception:
                    pass
        
        # Remove duplicates and return first valid email
        unique_emails = list(dict.fromkeys(emails_found))
        return unique_emails[0] if unique_emails else None
    
    def extract_logo(self, soup, base_url):
        """Extract logo URL from HTML"""
        logo_candidates = []
        
        # Method 1: Look for common logo class/id patterns
        logo_selectors = [
            'img.logo', '.logo img', '#logo img', 'img#logo',
            '.header img', '.navbar-brand img', '.site-logo img',
            'img[alt*="logo" i]', 'img[src*="logo" i]',
            '.logo a img', 'header .logo img', 'a.logo img',
            '.brand img', '.branding img', '.site-header img',
            'img[alt*="site" i]', 'img[alt*="brand" i]',
            'img[src*="brand" i]', 'a.navbar-brand img',
            'header a img', '#header img'
        ]
        
        for selector in logo_selectors:
            try:
                logo_elements = soup.select(selector)
                for logo_img in logo_elements:
                    if logo_img and logo_img.get('src'):
                        logo_url = urljoin(base_url, logo_img['src'])
                        if self.is_valid_image_url(logo_url):
                            logo_candidates.append((logo_url, self.score_logo_image(logo_img, "selector")))
            except Exception:
                continue
        
        # Method 2: Check meta tags for logos
        try:
            meta_icon = soup.find('link', rel=lambda x: x and ('icon' in x.lower() or 'shortcut' in x.lower()))
            if meta_icon and meta_icon.get('href'):
                icon_url = urljoin(base_url, meta_icon['href'])
                if self.is_valid_image_url(icon_url):
                    logo_candidates.append((icon_url, 10))  # Lower score for favicon
        except Exception:
            pass
            
        # Method 3: Find og:image meta tag
        try:
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                image_url = urljoin(base_url, og_image['content'])
                if self.is_valid_image_url(image_url):
                    logo_candidates.append((image_url, 30))
        except Exception:
            pass
        
        # Method 4: Find structured data
        try:
            for script in soup.find_all('script', type='application/ld+json'):
                if script.string:
                    import json
                    try:
                        data = json.loads(script.string)
                        if isinstance(data, dict):
                            logo = data.get('logo')
                            if logo and isinstance(logo, str):
                                logo_url = urljoin(base_url, logo)
                                if self.is_valid_image_url(logo_url):
                                    logo_candidates.append((logo_url, 80))
                    except Exception:
                        pass
        except Exception:
            pass
        
        # Sort by score (highest first) and return best candidate
        if logo_candidates:
            logo_candidates.sort(key=lambda x: x[1], reverse=True)
            return logo_candidates[0][0]
        
        return None
    
    def score_logo_image(self, img_tag, source_type):
        """Score potential logo images based on features"""
        score = 50  # Base score
        
        # Check for logo in attributes
        if img_tag.get('alt') and 'logo' in img_tag.get('alt', '').lower():
            score += 20
        if img_tag.get('src') and 'logo' in img_tag.get('src', '').lower():
            score += 15
        if img_tag.get('class') and any('logo' in c.lower() for c in img_tag.get('class', [])):
            score += 15
            
        # Dimensions often indicate a logo (if width/height attributes are present)
        try:
            width = int(img_tag.get('width', 0))
            height = int(img_tag.get('height', 0))
            if 20 <= width <= 400 and 20 <= height <= 200:
                score += 10
        except Exception:
            pass
            
        # Header/navbar logos are more likely to be actual logos
        if img_tag.parent and img_tag.parent.name == 'a':
            if img_tag.parent.get('href') == '/' or img_tag.parent.get('href') == '#':
                score += 15
        
        return score
    
    def is_valid_image_url(self, url):
        """Check if URL points to a valid image"""
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico']
        parsed_url = urlparse(url)
        return any(parsed_url.path.lower().endswith(ext) for ext in image_extensions)
    
    def extract_business_name(self, soup, url):
        """Extract business name from HTML"""
        candidates = []
        
        # Method 1: Check title tag (strongest signal)
        if soup.title:
            title = soup.title.text.strip()
            # Clean up title (remove common suffixes like "- Home" or "| Official Website")
            cleaned_title = re.sub(r'[-–|]\s*(.+?)$', '', title).strip()
            if cleaned_title:
                candidates.append((cleaned_title, 70))
        
        # Method 2: Look for common schema.org markup
        try:
            for script in soup.find_all('script', type='application/ld+json'):
                if script.string:
                    import json
                    try:
                        data = json.loads(script.string)
                        if isinstance(data, dict):
                            name = data.get('name')
                            if name and isinstance(name, str) and len(name) > 1:
                                candidates.append((name, 90))
                            
                            org_name = None
                            if data.get('publisher') and isinstance(data['publisher'], dict):
                                org_name = data['publisher'].get('name')
                            elif data.get('organization') and isinstance(data['organization'], dict):
                                org_name = data['organization'].get('name')
                            
                            if org_name and isinstance(org_name, str) and len(org_name) > 1:
                                candidates.append((org_name, 85))
                    except Exception:
                        pass
        except Exception:
            pass
        
        # Method 3: Look for common header patterns
        header_elements = [
            (soup.find('h1'), 60),
            (soup.select_one('.site-title'), 75),
            (soup.select_one('.brand'), 65),
            (soup.select_one('.company-name'), 80),
            (soup.select_one('header h1'), 70),
            (soup.select_one('.logo-title'), 75),
            (soup.select_one('.site-name'), 75)
        ]
        
        for element, score in header_elements:
            if element and element.text.strip():
                text = element.text.strip()
                if 2 <= len(text) <= 50:  # Reasonable name length
                    candidates.append((text, score))
        
        # Method 4: Extract from meta tags
        meta_elements = [
            ('og:site_name', 80),
            ('application-name', 75),
            ('twitter:title', 65),
            ('og:title', 60)
        ]
        
        for prop, score in meta_elements:
            meta_tag = soup.find('meta', {'property': prop}) or soup.find('meta', {'name': prop})
            if meta_tag and meta_tag.get('content'):
                content = meta_tag['content'].strip()
                if 2 <= len(content) <= 50:
                    candidates.append((content, score))
        
        # Method 5: Use domain name as fallback (lowest quality)
        domain = urlparse(url).netloc
        domain = domain.replace('www.', '')
        parts = domain.split('.')
        if len(parts) > 1:
            domain_name = parts[0].capitalize()
            if len(domain_name) >= 3:  # Exclude very short domains
                candidates.append((domain_name, 30))
        
        # Sort by score (highest first) and return best candidate
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        
        return None
    
    def extract_services(self, soup):
        """Extract services from HTML"""
        services = []
        
        # Method 1: Look for service sections
        service_selectors = [
            '.services', '#services', '.service-list', '.offerings',
            'section[id*="service" i]', 'div[class*="service" i]',
            '.what-we-do', '.products', 'ul.services-list',
            'div[id*="service" i]', '.service-area', '.our-services',
            'div[class*="leistung" i]', 'section[id*="leistung" i]',
            'div[id*="angebot" i]', 'section[id*="angebot" i]',
            'section[class*="leistung" i]', '.leistungen', '#leistungen',
            '.angebote', '#angebote', '.kompetenzen', '#kompetenzen',
            '.produkte', '#produkte', '.expertise', '#expertise',
            '.service-items', '.card-services', '.service-cards',
            'div[class*="service-item" i]', 'div[class*="dienstleistung" i]',
            'section[class*="dienstleistung" i]', '.dienstleistungen', 
            '#dienstleistungen'
        ]
        
        for selector in service_selectors:
            try:
                service_sections = soup.select(selector)
                for service_section in service_sections:
                    # Try to find list items, headings, or paragraphs within the section
                    elements = service_section.find_all(['li', 'h3', 'h4', 'h5', 'p', 'div.item', '.service-title', '.card-title'])
                    if elements:
                        for item in elements[:10]:  # Increased limit
                            service_text = item.text.strip()
                            # More aggressive filtering for relevant service texts
                            if service_text and 3 < len(service_text) < 120 and not self.is_common_element_text(service_text):
                                services.append(service_text)
                    
                    # Check for service cards/boxes (common pattern in modern sites)
                    service_cards = service_section.select('.card, .box, .item, .service-item, .service-box, .feature-box')
                    for card in service_cards[:8]:  # Limit to 8 cards
                        # Try to find title in the card
                        title_elem = card.select_one('h2, h3, h4, h5, .title, .card-title, .service-title, .heading')
                        if title_elem:
                            service_text = title_elem.text.strip()
                            if service_text and 3 < len(service_text) < 120 and not self.is_common_element_text(service_text):
                                services.append(service_text)
            except Exception:
                continue
        
        # Method 2: Look for headings in sections that might contain services
        if len(services) < 3:  # If few services found, try deeper analysis
            service_keywords = [
                'service', 'leistung', 'angebot', 'offering', 'solution', 
                'dienstleistung', 'produkt', 'capability', 'kompetenzen', 
                'expertise', 'wir bieten', 'angebote', 'solutions', 
                'unsere leistungen', 'was wir tun', 'what we do'
            ]
            potential_headings = soup.find_all(['h1', 'h2', 'h3', 'h4'], limit=20)
            
            for heading in potential_headings:
                heading_text = heading.text.lower()
                if any(keyword in heading_text for keyword in service_keywords):
                    # Get the next section that might contain lists or paragraphs
                    siblings = self.get_next_siblings_until_heading(heading)
                    
                    for sibling in siblings:
                        # Check for lists (very common for services)
                        if sibling.name in ['ul', 'ol']:
                            items = sibling.find_all('li', limit=12)
                            for item in items:
                                service_text = item.text.strip()
                                if service_text and 3 < len(service_text) < 120 and not self.is_common_element_text(service_text):
                                    services.append(service_text)
                        
                        # Check for divs that might contain service lists/cards
                        elif sibling.name == 'div':
                            # Look for paragraphs, list items, or smaller headings
                            elements = sibling.find_all(['p', 'li', 'h4', 'h5', '.card', '.box', '.item', '.service-item'], limit=12)
                            for element in elements:
                                service_text = element.text.strip()
                                if service_text and 3 < len(service_text) < 120 and not self.is_common_element_text(service_text):
                                    services.append(service_text)
                        
                        # Look for grids/rows which often contain service cards
                        elif sibling.get('class') and any(c in ' '.join(sibling.get('class', [])).lower() for c in ['row', 'grid', 'flex', 'container']):
                            items = sibling.select('.col, .card, .box, .item, .service-item, .grid-item, [class*="col-"]')
                            for item in items[:8]:
                                # Try to find title in the item
                                title_elem = item.select_one('h2, h3, h4, h5, .title, .card-title, .service-title, .heading')
                                if title_elem:
                                    service_text = title_elem.text.strip()
                                    if service_text and 3 < len(service_text) < 120 and not self.is_common_element_text(service_text):
                                        services.append(service_text)
        
        # Method 3: Look for paragraphs following service-related keywords
        if len(services) < 2:  # If still few services found
            service_paragraphs = []
            paragraphs = soup.find_all('p', limit=30)
            
            service_phrases = [
                'we offer', 'our services', 'wir bieten', 'unsere leistungen',
                'our products', 'our solutions', 'our expertise', 
                'unsere produkte', 'unsere angebote', 'unsere kompetenzen',
                'what we do', 'was wir tun', 'how we help', 'wie wir helfen'
            ]
            
            for p in paragraphs:
                p_text = p.text.lower()
                if any(phrase in p_text for phrase in service_phrases):
                    service_paragraphs.append(p)
                    
                    # Get following paragraphs
                    next_sibling = p.find_next_sibling()
                    if next_sibling and next_sibling.name == 'p':
                        service_paragraphs.append(next_sibling)
            
            for p in service_paragraphs:
                # Try to extract services from paragraphs
                text = p.text.strip()
                if text:
                    # Split by common separators
                    for splitter in [',', '•', '|', ';', '.', '/', '–', '-']:
                        if splitter in text:
                            parts = [part.strip() for part in text.split(splitter)]
                            for part in parts:
                                if 3 < len(part) < 80 and not self.is_common_element_text(part):
                                    services.append(part)
                            break
                    
                    # If no separators, use the whole paragraph if it's short enough
                    if len(text) < 120 and len(services) < 2:
                        services.append(text)
        
        # Method 4: Check meta description for service clues
        if len(services) < 2:
            meta_desc = soup.find('meta', {'name': 'description'}) or soup.find('meta', {'property': 'og:description'})
            if meta_desc and meta_desc.get('content'):
                desc_text = meta_desc['content'].strip()
                # Look for service patterns in meta description
                service_patterns = [
                    r'(?:we offer|wir bieten|our services|unsere leistungen)[:\s]+([^.]+)',
                    r'(?:specialist in|spezialisiert auf|experts in|experten für)[:\s]+([^.]+)'
                ]
                
                for pattern in service_patterns:
                    matches = re.search(pattern, desc_text, re.IGNORECASE)
                    if matches:
                        service_text = matches.group(1).strip()
                        # Split into multiple services if delimiters exist
                        for splitter in [',', '•', '|', ';', '/', '&', 'and', 'und']:
                            if splitter in service_text:
                                parts = [part.strip() for part in service_text.split(splitter)]
                                for part in parts:
                                    if 3 < len(part) < 80 and not self.is_common_element_text(part):
                                        services.append(part)
                                break
                        else:
                            # If no splitters found
                            if 3 < len(service_text) < 120 and not self.is_common_element_text(service_text):
                                services.append(service_text)
        
        # Return unique services, limited to 15
        clean_services = []
        for service in services:
            # Clean up service text (remove extra whitespace, newlines, etc.)
            clean_text = ' '.join(service.split())
            
            # Skip very short services or duplicates
            if len(clean_text) <= 3 or clean_text.lower() in [s.lower() for s in clean_services]:
                continue
                
            # Check for high similarity with existing services to avoid near-duplicates
            if any(self.text_similarity(clean_text, existing) > 0.8 for existing in clean_services):
                continue
                
            clean_services.append(clean_text)
                
        return clean_services[:15]
    
    def text_similarity(self, text1, text2):
        """Calculate simple similarity between two texts"""
        # Convert to lowercase for comparison
        text1 = text1.lower()
        text2 = text2.lower()
        
        # If one is fully contained in the other, high similarity
        if text1 in text2 or text2 in text1:
            return 0.9
            
        # Count common words
        words1 = set(text1.split())
        words2 = set(text2.split())
        common_words = words1.intersection(words2)
        
        # Calculate Jaccard similarity
        if not words1 or not words2:
            return 0
            
        return len(common_words) / len(words1.union(words2))
    
    def get_next_siblings_until_heading(self, element):
        """Get siblings until next heading of same or higher level"""
        siblings = []
        current = element.find_next_sibling()
        
        # Get the heading level (h1=1, h2=2, etc.)
        try:
            heading_level = int(element.name[1])
        except (ValueError, IndexError):
            heading_level = 10  # Not a heading, set high level
        
        while current:
            # Stop if we hit another heading of same or higher level
            if current.name in ['h1', 'h2', 'h3'] and int(current.name[1]) <= heading_level:
                break
            siblings.append(current)
            current = current.find_next_sibling()
            
        return siblings
    
    def is_common_element_text(self, text):
        """Check if text appears to be a non-service element"""
        text_lower = text.lower()
        common_elements = [
            'home', 'contact', 'about', 'menu', 'search', 'login', 'register',
            'startseite', 'kontakt', 'über uns', 'anmelden', 'registrieren',
            'cookie', 'privacy', 'datenschutz', 'impressum', 'agb', 'faq',
            'read more', 'learn more', 'mehr erfahren', 'mehr lesen',
            'submit', 'send', 'download', 'blog', 'news', 'article', 'post',
            'abschicken', 'senden', 'herunterladen', 'artikel', 'nachricht',
            'click here', 'hier klicken', 'next', 'previous', 'weiter', 'zurück',
            'aktuelles', 'termine', 'events', 'veranstaltungen'
        ]
        
        return any(elem in text_lower for elem in common_elements) or len(text_lower) < 4
    
    def scrape_website(self, url):
        """Scrape a single website URL"""
        result = {
            'url': url,
            'email': None,
            'logo': None,
            'business_name': None,
            'services': None,
            'error': None
        }
        
        try:
            # Add a small random delay to prevent overloading servers and potential blocking
            time.sleep(random.uniform(0.5, 2.0))
            
            response = self.session.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            # Handle encoding for German umlauts
            if 'charset' not in response.headers.get('content-type', '').lower():
                response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract data
            result['email'] = self.extract_email(soup, response.text, url)
            result['logo'] = self.extract_logo(soup, url)
            result['business_name'] = self.extract_business_name(soup, url)
            
            services = self.extract_services(soup)
            if services:
                # Ensure all services are strings before joining
                string_services = [str(service) for service in services if service is not None]
                result['services'] = '; '.join(string_services)
            
        except requests.exceptions.RequestException as e:
            result['error'] = f"Request error: {str(e)}"
            logging.warning(f"Error scraping {url}: {str(e)}")
        except Exception as e:
            result['error'] = f"Error: {str(e)}"
            logging.warning(f"Error scraping {url}: {str(e)}")
        
        return result
    
    def process_batch(self, urls):
        """Process a batch of URLs using concurrent.futures"""
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {executor.submit(self.scrape_website, url): url for url in urls}
            for future in tqdm(concurrent.futures.as_completed(future_to_url), total=len(future_to_url), desc="Scraping websites"):
                results.append(future.result())
        return results
    
    def run(self):
        """Main execution method"""
        urls = self.load_urls()
        if urls is None:
            return
        
        logging.info(f"Starting to scrape {len(urls)} websites")
        
        # Process URLs
        results = self.process_batch(urls['url'].tolist())
        
        # Create DataFrame from results
        df = pd.DataFrame(results)
        
        # Save updated DataFrame
        self.save_results(df)
        
        # Log statistics
        success_count = sum(1 for r in results if r['error'] is None)
        logging.info(f"Scraping completed. Success: {success_count}/{len(results)}")

if __name__ == "__main__":
    scraper = WebsiteScraper('leads.csv')
    scraper.run() 