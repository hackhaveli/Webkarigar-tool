from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
import pandas as pd
import os
from scraper import WebsiteScraper
import threading
import time
from werkzeug.utils import secure_filename
import io
import csv
import zipfile
import requests
import json
import shutil
from urllib.parse import urlparse
import glob
import re
import logging
from datetime import datetime
# Import the email sender module
import email_sender
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
import queue
import random
import string
import secrets
import tempfile
import platform
import traceback
import subprocess

# Import configuration
try:
    from config import FTP_CONFIG, DEPLOYED_URL_BASE, STARTING_SITE_ID
except ImportError:
    # Default configuration if config.py doesn't exist
    FTP_CONFIG = {
        'host': 'your-ftp-server.com',
        'username': 'your-username',
        'password': 'your-password',
        'base_path': '/jede-website-info.de/',
        'use_sftp': False,
        'port': 21
    }
    DEPLOYED_URL_BASE = 'https://jede-website-info.de/'
    STARTING_SITE_ID = 1111110

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # For session/flash messages

# Register the email sender blueprint
from email_sender import email_sender_bp
app.register_blueprint(email_sender_bp, url_prefix='/email_campaign')

@app.route('/email_campaign')
def email_campaign():
    return redirect(url_for('email_sender.email_sender_page'))

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    filename='app.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Global variable to track scraping progress
scraping_status = {
    "is_running": False,
    "total": 0,
    "completed": 0,
    "success": 0,
    "failed": 0,
    "start_time": None
}

# Global variable to track temp files
temp_files = {
    "last_cleanup": time.time()
}

def cleanup_temp_files():
    """Periodically clean up temporary files that are older than 1 hour"""
    try:
        # Check if we need to run cleanup (every hour)
        current_time = time.time()
        if current_time - temp_files["last_cleanup"] < 3600:  # 1 hour
            return
        
        temp_files["last_cleanup"] = current_time
        
        # Find all temp files older than 1 hour
        for temp_file in glob.glob('*.zip'):
            # Only process our generated zip files
            if temp_file.startswith(('website_templates_', 'scraped_data_')):
                file_time = os.path.getmtime(temp_file)
                # If file is older than 1 hour (3600 seconds)
                if current_time - file_time > 3600:
                    try:
                        os.remove(temp_file)
                        print(f"Cleaned up old temp file: {temp_file}")
                    except Exception as e:
                        print(f"Error removing temp file {temp_file}: {str(e)}")
        
        # Schedule next cleanup
        threading.Timer(3600, cleanup_temp_files).start()
        
    except Exception as e:
        print(f"Error during temp file cleanup: {str(e)}")

# Start cleanup thread when application starts
threading.Timer(3600, cleanup_temp_files).start()

def run_scraper_thread(csv_path, max_workers):
    global scraping_status
    
    scraping_status["is_running"] = True
    scraping_status["start_time"] = time.time()
    
    try:
        # Get total number of URLs
        df = pd.read_csv(csv_path)
        total_urls = len(df)
        scraping_status["total"] = total_urls
        
        # Create a custom scraper that updates the status
        class StatusUpdateScraper(WebsiteScraper):
            def scrape_website(self, url):
                result = super().scrape_website(url)
                
                # Update status after each scrape
                global scraping_status
                scraping_status["completed"] += 1
                if result["error"] is None:
                    scraping_status["success"] += 1
                else:
                    scraping_status["failed"] += 1
                
                return result
        
        # Run the scraper
        scraper = StatusUpdateScraper(csv_path, max_workers=max_workers)
        scraper.run()
        
    except Exception as e:
        print(f"Scraper error: {str(e)}")
    finally:
        scraping_status["is_running"] = False

@app.route('/')
def index():
    # Check if the CSV file exists
    csv_exists = os.path.exists('leads.csv')
    
    # If CSV exists, read and pass data to template
    data = None
    url_stats = {
        'total': 0,
        'with_urls': 0,
        'missing_urls': 0
    }
    if csv_exists:
        try:
            df = pd.read_csv('leads.csv')
            
            # Ensure we have all required columns
            required_columns = ['url', 'email', 'logo', 'business_name', 'services', 'error']
            for col in required_columns:
                if col not in df.columns:
                    df[col] = None
            
            data = df.to_dict('records')
            
            # Calculate URL statistics
            url_stats['total'] = len(df)
            if 'template_url' in df.columns:
                url_stats['with_urls'] = df['template_url'].notna().sum()
                url_stats['missing_urls'] = url_stats['total'] - url_stats['with_urls']
        except Exception as e:
            flash(f"Error reading CSV: {str(e)}", 'danger')
    
    return render_template('index.html', data=data, scraping_status=scraping_status, url_stats=url_stats)

@app.route('/start_scraping', methods=['POST'])
def start_scraping():
    global scraping_status
    
    if scraping_status["is_running"]:
        flash('A scraping job is already running!', 'warning')
        return redirect(url_for('index'))
    
    # Reset status
    scraping_status = {
        "is_running": False,
        "total": 0,
        "completed": 0,
        "success": 0,
        "failed": 0,
        "start_time": None
    }
    
    # Get max workers from form
    max_workers = int(request.form.get('max_workers', 5))
    
    # Start scraper in a thread
    thread = threading.Thread(
        target=run_scraper_thread,
        args=('leads.csv', max_workers)
    )
    thread.daemon = True
    thread.start()
    
    flash('Scraping started!', 'success')
    return redirect(url_for('index'))

@app.route('/status')
def status():
    return jsonify(scraping_status)

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    if 'csv_file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('index'))
        
    file = request.files['csv_file']
    
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('index'))
        
    if file and file.filename.endswith('.csv'):
        try:
            # Secure the filename
            filename = secure_filename(file.filename)
            temp_path = os.path.join('temp_' + filename)
            
            # Save temporarily to validate
            file.save(temp_path)
            
            # Read and validate CSV
            try:
                df = pd.read_csv(temp_path)
                
                # Check if 'url' column exists
                if 'url' not in df.columns:
                    # If not, check if the file has a column without a header
                    # or tries to handle the case where data in first row
                    if len(df.columns) > 0:
                        # Try to interpret first column as URLs
                        first_col = df.columns[0]
                        df = pd.DataFrame({
                            'url': [first_col] + df[first_col].tolist()
                        })
                    else:
                        raise ValueError("CSV must contain a column named 'url' or have URLs in first column")
                
                # Normalize URLs (add https:// if missing)
                def normalize_url(url):
                    if not str(url).startswith(('http://', 'https://')):
                        return 'https://' + str(url)
                    return url
                
                df['url'] = df['url'].apply(normalize_url)
                
                # Ensure we have all required columns
                required_columns = ['url', 'email', 'logo', 'business_name', 'services', 'error']
                for col in required_columns:
                    if col not in df.columns:
                        df[col] = None
                
                # Save the processed file
                df.to_csv('leads.csv', index=False)
                
                flash(f'File uploaded successfully with {len(df)} URLs', 'success')
            except Exception as e:
                # If pandas fails, try with CSV module for more basic CSV files
                try:
                    with open(temp_path, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        rows = list(reader)
                        
                        # Check if there's a header row
                        has_header = 'url' in rows[0] if rows else False
                        
                        urls = []
                        if has_header:
                            # Get index of url column
                            url_idx = rows[0].index('url')
                            urls = [row[url_idx] for row in rows[1:] if len(row) > url_idx]
                        else:
                            # Assume first column is URL
                            urls = [row[0] for row in rows if row]
                        
                        # Create a new DataFrame with the extracted URLs
                        df = pd.DataFrame({'url': urls})
                        
                        # Normalize URLs
                        df['url'] = df['url'].apply(normalize_url)
                        
                        # Add required columns
                        for col in ['email', 'logo', 'business_name', 'services', 'error']:
                            df[col] = None
                        
                        # Save the processed file
                        df.to_csv('leads.csv', index=False)
                        
                        flash(f'File processed successfully with {len(df)} URLs', 'success')
                except Exception as e2:
                    raise ValueError(f"Error processing file: {str(e)}, {str(e2)}")
            
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'danger')
    else:
        flash('File must be a CSV', 'danger')
        
    return redirect(url_for('index'))

@app.route('/download_csv')
def download_csv():
    """Download the current results as a CSV file"""
    try:
        # Check if the CSV file exists
        if not os.path.exists('leads.csv'):
            flash('No data to download', 'warning')
            return redirect(url_for('index'))
        
        # Read the CSV and create a download
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        return send_file(
            'leads.csv',
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'scraped_data_{timestamp}.csv'
        )
    except Exception as e:
        flash(f'Error downloading file: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/download_all_data')
def download_all_data():
    """Download all scraped data including logos in a folder structure"""
    try:
        # Check if the CSV file exists
        if not os.path.exists('leads.csv'):
            flash('No data to download', 'warning')
            return redirect(url_for('index'))
        
        # Create a timestamp for the download folder
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        base_folder = f'scraped_data_{timestamp}'
        
        # Create base folder if it doesn't exist
        if os.path.exists(base_folder):
            shutil.rmtree(base_folder)
        os.makedirs(base_folder)
        
        # Read the CSV file
        df = pd.read_csv('leads.csv')
        
        # Process each site
        for index, row in df.iterrows():
            url = row['url']
            if pd.isna(url) or not url:
                continue
            
            # Create a safe folder name based on business name or domain
            if pd.notna(row['business_name']) and row['business_name']:
                folder_name = secure_filename(row['business_name'])
            else:
                # Extract domain from URL
                domain = urlparse(url).netloc
                folder_name = secure_filename(domain)
            
            # Ensure folder name is unique
            site_folder = os.path.join(base_folder, folder_name)
            counter = 1
            original_folder = site_folder
            while os.path.exists(site_folder):
                site_folder = f"{original_folder}_{counter}"
                counter += 1
            
            # Create folder for this site
            os.makedirs(site_folder)
            
            # Download logo if available
            logo_path = None
            if pd.notna(row['logo']) and row['logo']:
                try:
                    logo_url = row['logo']
                    logo_filename = os.path.basename(urlparse(logo_url).path)
                    if not logo_filename or '.' not in logo_filename:
                        logo_filename = 'logo.png'
                    logo_path = os.path.join(site_folder, logo_filename)
                    
                    # Download the logo
                    response = requests.get(logo_url, stream=True, timeout=10)
                    if response.status_code == 200:
                        with open(logo_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                except Exception as e:
                    print(f"Error downloading logo for {url}: {str(e)}")
                    logo_path = None
            
            # Create a details file
            details_file = os.path.join(site_folder, 'details.txt')
            with open(details_file, 'w', encoding='utf-8') as f:
                f.write(f"URL: {url}\n")
                f.write(f"Business Name: {row['business_name'] if pd.notna(row['business_name']) else 'N/A'}\n")
                f.write(f"Email: {row['email'] if pd.notna(row['email']) else 'N/A'}\n")
                f.write(f"Logo: {os.path.basename(logo_path) if logo_path else 'N/A'}\n")
                f.write(f"Services:\n")
                if pd.notna(row['services']) and row['services']:
                    services = row['services'].split(';')
                    for idx, service in enumerate(services, 1):
                        f.write(f"  {idx}. {service.strip()}\n")
                else:
                    f.write("  No services found\n")
                
                if pd.notna(row['error']) and row['error']:
                    f.write(f"\nErrors: {row['error']}\n")
            
            # Create a JSON file with all data
            json_file = os.path.join(site_folder, 'data.json')
            site_data = {
                'url': url,
                'business_name': row['business_name'] if pd.notna(row['business_name']) else urlparse(url).netloc,
                'email': row['email'] if pd.notna(row['email']) else None,
                'logo': logo_filename,  # Just the filename, not the full path
                'logo_file': os.path.basename(logo_path) if logo_path else None,
                'services': row['services'].split(';') if pd.notna(row['services']) and row['services'] else [],
                'error': row['error'] if pd.notna(row['error']) else None
            }
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(site_data, f, indent=2, ensure_ascii=False)
        
        # Create an index.html file in the root folder
        index_html = os.path.join(base_folder, 'index.html')
        with open(index_html, 'w', encoding='utf-8') as f:
            f.write('<!DOCTYPE html>\n<html>\n<head>\n')
            f.write('<meta charset="UTF-8">\n')
            f.write('<title>Scraped Websites</title>\n')
            f.write('<style>\n')
            f.write('body { font-family: Arial, sans-serif; margin: 20px; }\n')
            f.write('h1 { color: #2196F3; }\n')
            f.write('table { border-collapse: collapse; width: 100%; }\n')
            f.write('th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }\n')
            f.write('th { background-color: #f2f2f2; }\n')
            f.write('tr:nth-child(even) { background-color: #f9f9f9; }\n')
            f.write('img.logo { max-height: 40px; max-width: 100px; }\n')
            f.write('</style>\n</head>\n<body>\n')
            f.write('<h1>Scraped Websites</h1>\n')
            f.write('<p>Generated on: ' + time.strftime("%Y-%m-%d %H:%M:%S") + '</p>\n')
            f.write('<table>\n')
            f.write('<tr><th>#</th><th>Website</th><th>Business Name</th><th>Email</th><th>Logo</th><th>Services</th></tr>\n')
            
            # Add a row for each site
            for index, row in df.iterrows():
                url = row['url']
                if pd.isna(url) or not url:
                    continue
                
                if pd.notna(row['business_name']) and row['business_name']:
                    folder_name = secure_filename(row['business_name'])
                else:
                    domain = urlparse(url).netloc
                    folder_name = secure_filename(domain)
                
                # Find the actual folder
                site_folder_actual = folder_name
                counter = 1
                while not os.path.exists(os.path.join(base_folder, site_folder_actual)) and counter < 10:
                    site_folder_actual = f"{folder_name}_{counter}"
                    counter += 1
                
                # Get logo path if it exists
                logo_html = "N/A"
                logo_files = [f for f in os.listdir(os.path.join(base_folder, site_folder_actual)) 
                             if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))]
                if logo_files:
                    logo_file = logo_files[0]
                    logo_html = f'<img src="{site_folder_actual}/{logo_file}" class="logo" alt="Logo">'
                
                # Services
                services_html = "N/A"
                if pd.notna(row['services']) and row['services']:
                    services = row['services'].split(';')
                    if len(services) > 2:
                        services_html = f"{services[0].strip()}; {services[1].strip()}..."
                    else:
                        services_html = '; '.join(s.strip() for s in services)
                
                # Add the row
                f.write(f'<tr>\n')
                f.write(f'<td>{index+1}</td>\n')
                f.write(f'<td><a href="{url}" target="_blank">{urlparse(url).netloc}</a><br>')
                f.write(f'<a href="{site_folder_actual}/details.txt">Details</a> | ')
                f.write(f'<a href="{site_folder_actual}/data.json">JSON</a></td>\n')
                f.write(f'<td>{row["business_name"] if pd.notna(row["business_name"]) else "N/A"}</td>\n')
                f.write(f'<td>{row["email"] if pd.notna(row["email"]) else "N/A"}</td>\n')
                f.write(f'<td>{logo_html}</td>\n')
                f.write(f'<td>{services_html}</td>\n')
                f.write('</tr>\n')
            
            f.write('</table>\n</body>\n</html>')
        
        # Create a zip file with all data
        zip_filename = f'{base_folder}.zip'
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(base_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, os.path.dirname(base_folder)))
        
        # Clean up the folder after zipping
        shutil.rmtree(base_folder)
        
        # Return the zip file
        return send_file(
            zip_filename,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )
    except Exception as e:
        print(f"Error: {str(e)}")
        flash(f'Error preparing download: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/generate_templates')
def generate_templates():
    """Generate three website templates for each scraped website"""
    try:
        # Check if the CSV file exists
        if not os.path.exists('leads.csv'):
            flash('No data to generate templates from', 'warning')
            return redirect(url_for('index'))
        
        # Create a timestamp for the download folder
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        base_folder = f'website_templates_{timestamp}'
        
        # Create base folder if it doesn't exist
        if os.path.exists(base_folder):
            shutil.rmtree(base_folder)
        os.makedirs(base_folder)
        
        # Read the CSV file
        df = pd.read_csv('leads.csv')
        
        # Template styles
        template_styles = [
            {
                'name': 'modern',
                'primary_color': '#4285F4',
                'secondary_color': '#34A853',
                'font': "'Roboto', sans-serif",
                'style_class': 'modern-template'
            },
            {
                'name': 'elegant',
                'primary_color': '#333333',
                'secondary_color': '#B8860B',
                'font': "'Playfair Display', serif",
                'style_class': 'elegant-template'
            },
            {
                'name': 'minimalist',
                'primary_color': '#000000',
                'secondary_color': '#FFFFFF',
                'accent_color': '#F44336',
                'font': "'Open Sans', sans-serif",
                'style_class': 'minimalist-template'
            }
        ]
        
        # Track successfully processed sites and errors
        processed_sites = 0
        skipped_sites = 0
        errors = []
        
        # Dictionary to store site IDs for deployment
        site_mappings = {}
        
        # Process each site
        for index, row in df.iterrows():
            try:
                # Defensive: sanitize all fields used for folder and file names
                def safe_str(val):
                    if pd.isna(val):
                        return ''
                    if isinstance(val, dict):
                        return json.dumps(val)
                    return str(val)

                url = safe_str(row['url'])
                business_name = safe_str(row['business_name'])
                logo = safe_str(row['logo'])
                email = safe_str(row['email'])
                services = safe_str(row['services'])

                if not url:
                    continue
                
                # Create a safe folder name based on business name or domain
                if business_name:
                    folder_name = secure_filename(business_name)
                else:
                    domain = urlparse(url).netloc
                    folder_name = secure_filename(domain)
                
                # Ensure folder name is unique
                site_folder = os.path.join(base_folder, folder_name)
                counter = 1
                original_folder = site_folder
                while os.path.exists(site_folder):
                    site_folder = f"{original_folder}_{counter}"
                    counter += 1
                
                # Generate a unique ID for deployment
                site_id = get_next_site_id()
                site_mappings[folder_name] = site_id
                
                # Create folder for this site
                os.makedirs(site_folder)
                
                # Download logo if available
                logo_path = None
                logo_filename = None
                if logo:
                    try:
                        logo_url = logo
                        logo_filename = os.path.basename(urlparse(logo_url).path)
                        if not logo_filename or '.' not in logo_filename:
                            logo_filename = 'logo.png'
                        logo_path = os.path.join(site_folder, logo_filename)
                        
                        # Download the logo
                        response = requests.get(logo_url, stream=True, timeout=10)
                        if response.status_code == 200:
                            with open(logo_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    f.write(chunk)
                        else:
                            # If download fails, set to None to avoid further errors
                            logo_path = None
                            logo_filename = None
                    except Exception as e:
                        print(f"Error downloading logo for {url}: {str(e)}")
                        # If an error occurs, set to None to avoid further errors
                        logo_path = None
                        logo_filename = None
                
                # Extract site data
                site_data = {
                    'url': url,
                    'business_name': business_name if business_name else urlparse(url).netloc,
                    'email': email if email else None,
                    'logo': logo_filename,  # Just the filename, not the full path
                    'services': [s.strip() for s in services.split(';')] if services else [],
                    'site_id': site_id  # Add the site ID to site data
                }
                
                # Generate templates in different styles
                for style in template_styles:
                    # Use style name rather than the entire style dictionary for the folder name
                    template_folder = os.path.join(site_folder, style['name'])
                    os.makedirs(template_folder)
                    
                    # Create index.html
                    generate_template_html(template_folder, site_data, style)
                    
                    # Create styles.css
                    generate_template_css(template_folder, style)
                    
                    # Copy logo if available
                    if logo_path and os.path.exists(logo_path):
                        try:
                            shutil.copy(logo_path, os.path.join(template_folder, logo_filename))
                        except Exception as e:
                            print(f"Error copying logo to template folder: {str(e)}")
                            # Continue even if logo copying fails
                
                processed_sites += 1
                
            except Exception as e:
                error_msg = f"Error processing site {url if 'url' in locals() else f'at index {index}'}: {str(e)}"
                print(error_msg)
                errors.append(error_msg)
                skipped_sites += 1
                continue  # Skip to the next site
        
        # Create an index.html in the root folder
        index_html = os.path.join(base_folder, 'index.html')
        with open(index_html, 'w', encoding='utf-8') as f:
            f.write('<!DOCTYPE html>\n<html>\n<head>\n')
            f.write('<meta charset="UTF-8">\n')
            f.write('<meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
            f.write('<title>Generated Templates</title>\n')
            f.write('<style>\n')
            f.write('body { font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }\n')
            f.write('h1 { color: #2196F3; }\n')
            f.write('.site-card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }\n')
            f.write('.templates { display: flex; flex-wrap: wrap; gap: 15px; margin-top: 10px; }\n')
            f.write('.template-preview { border: 1px solid #eee; border-radius: 5px; padding: 10px; width: 200px; text-align: center; }\n')
            f.write('.template-preview img { max-width: 100%; height: auto; margin-bottom: 10px; border: 1px solid #eee; }\n')
            f.write('.template-preview a { display: inline-block; margin-top: 5px; text-decoration: none; color: white; background-color: #2196F3; padding: 5px 10px; border-radius: 3px; }\n')
            f.write('.template-preview a:hover { background-color: #0b7dda; }\n')
            f.write('.stats { background-color: #f9f9f9; padding: 15px; border-radius: 5px; margin-bottom: 20px; }\n')
            f.write('.site-id { font-size: 0.9em; color: #666; margin-top: 5px; }\n')  # Add style for site ID
            f.write('</style>\n</head>\n<body>\n')
            f.write('<h1>Generated Website Templates</h1>\n')
            f.write('<p>Generated on: ' + time.strftime("%Y-%m-%d %H:%M:%S") + '</p>\n')
            
            # Add stats
            f.write('<div class="stats">\n')
            f.write(f'<p><strong>Total sites processed:</strong> {processed_sites}</p>\n')
            if skipped_sites > 0:
                f.write(f'<p><strong>Sites skipped due to errors:</strong> {skipped_sites}</p>\n')
            f.write('</div>\n')
            
            # If there were errors, list them
            if errors:
                f.write('<div class="errors" style="margin-bottom: 20px; color: #721c24; background-color: #f8d7da; padding: 15px; border-radius: 5px;">\n')
                f.write('<h3>Errors encountered:</h3>\n<ul>\n')
                for error in errors[:10]:  # Show first 10 errors
                    f.write(f'<li>{error}</li>\n')
                if len(errors) > 10:
                    f.write(f'<li>...and {len(errors) - 10} more errors</li>\n')
                f.write('</ul>\n</div>\n')
            
            # List each site
            site_folders = [f for f in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, f)) and f != '__pycache__']
            for site_folder in site_folders:
                f.write(f'<div class="site-card">\n')
                f.write(f'<h2>{site_folder}</h2>\n')
                
                # Add site ID if available
                if site_folder in site_mappings:
                    f.write(f'<p class="site-id">Site ID: {site_mappings[site_folder]}</p>\n')
                    f.write(f'<p class="site-id">Live URL: {DEPLOYED_URL_BASE}{site_mappings[site_folder]}/</p>\n')
                
                f.write('<div class="templates">\n')
                
                style_folders = [s for s in os.listdir(os.path.join(base_folder, site_folder)) 
                               if os.path.isdir(os.path.join(base_folder, site_folder, s))]
                
                for style in style_folders:
                    template_path = os.path.join(site_folder, style)
                    f.write(f'<div class="template-preview">\n')
                    f.write(f'<h3>{style.capitalize()}</h3>\n')
                    
                    # Add a preview link
                    f.write(f'<a href="{template_path}/index.html" target="_blank">View Template</a>\n')
                    
                    # Add deployed link if available
                    if site_folder in site_mappings:
                        f.write(f'<a href="{DEPLOYED_URL_BASE}{site_mappings[site_folder]}/{style}/index.html" target="_blank" style="background-color: #4CAF50; margin-top: 5px;">View Live</a>\n')
                    
                    f.write('</div>\n')
                
                f.write('</div>\n')
                f.write('</div>\n')
            
            f.write('</body>\n</html>')
        
        # Create a zip file with all templates
        zip_filename = f'{base_folder}.zip'
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(base_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, os.path.dirname(base_folder)))
        
        # Save the site mappings for future reference
        with open('site_id_mappings.json', 'w') as f:
            json.dump(site_mappings, f)
        
        # Clean up the folder after zipping
        shutil.rmtree(base_folder)
        
        # Flash message with results
        flash(f'Successfully generated templates for {processed_sites} websites. ' +
              (f'{skipped_sites} sites were skipped due to errors.' if skipped_sites > 0 else ''), 
              'success' if skipped_sites == 0 else 'warning')
        
        # Return the zip file
        return send_file(
            zip_filename,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )
    except Exception as e:
        print(f"Error generating templates: {str(e)}")
        flash(f'Error generating templates: {str(e)}', 'danger')
        return redirect(url_for('index'))

def generate_template_html(template_folder, site_data, style):
    """Generate HTML template for a website"""
    html_file = os.path.join(template_folder, 'index.html')
    
    # Get business name and default if not available
    business_name = site_data['business_name']
    
    # Create HTML content
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{business_name}</title>
    <link rel="stylesheet" href="styles.css">
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&family=Playfair+Display:wght@400;700&family=Open+Sans:wght@300;400;700&display=swap" rel="stylesheet">
</head>
<body class="{style['style_class']}">
    <header>
        <div class="container">
'''
    
    # Add logo if available
    if site_data['logo']:
        html_content += f'            <div class="logo"><img src="{site_data["logo"]}" alt="{business_name} Logo"></div>\n'
    
    html_content += f'''            <h1>{business_name}</h1>
            <nav>
                <ul>
                    <li><a href="#home">Home</a></li>
                    <li><a href="#services">Services</a></li>
                    <li><a href="#about">About</a></li>
                    <li><a href="#contact">Contact</a></li>
                </ul>
            </nav>
        </div>
    </header>

    <section id="home" class="hero">
        <div class="container">
            <h2>Welcome to {business_name}</h2>
            <p class="tagline">Your trusted partner for'''
    
    # Add up to 3 services if available
    services_to_show = site_data['services'][:3] if site_data['services'] else ['professional services']
    for i, service in enumerate(services_to_show):
        if i == len(services_to_show) - 1 and i > 0:
            html_content += f' and {service.strip()}'
        elif i > 0:
            html_content += f', {service.strip()}'
        else:
            html_content += f' {service.strip()}'
    
    html_content += '''</p>
            <a href="#contact" class="cta-button">Get in Touch</a>
        </div>
    </section>

    <section id="services" class="services">
        <div class="container">
            <h2>Our Services</h2>
            <div class="services-grid">'''
    
    # Add services
    if site_data['services']:
        for service in site_data['services']:
            html_content += f'''
                <div class="service-card">
                    <h3>{service.strip()}</h3>
                    <p>We provide high-quality {service.strip().lower()} services tailored to your specific needs.</p>
                </div>'''
    else:
        html_content += '''
                <div class="service-card">
                    <h3>Service 1</h3>
                    <p>Description of our first service offering.</p>
                </div>
                <div class="service-card">
                    <h3>Service 2</h3>
                    <p>Description of our second service offering.</p>
                </div>
                <div class="service-card">
                    <h3>Service 3</h3>
                    <p>Description of our third service offering.</p>
                </div>'''
    
    html_content += '''
            </div>
        </div>
    </section>

    <section id="about" class="about">
        <div class="container">
            <h2>About Us</h2>
            <p>At '''
    
    html_content += f'''{business_name}, we are committed to providing exceptional service and building lasting relationships with our clients. With years of experience in the industry, we have the expertise and knowledge to meet your needs.</p>
            <p>Our team of professionals is dedicated to delivering the highest quality solutions, and we take pride in our attention to detail and customer satisfaction.</p>
        </div>
    </section>

    <section id="contact" class="contact">
        <div class="container">
            <h2>Contact Us</h2>
            <div class="contact-info">'''
    
    # Add email if available
    if site_data['email']:
        html_content += f'''
                <div class="contact-item">
                    <h3>Email</h3>
                    <p><a href="mailto:{site_data['email']}">{site_data['email']}</a></p>
                </div>'''
    
    html_content += '''
                <div class="contact-item">
                    <h3>Address</h3>
                    <p>123 Main Street<br>City, State 12345</p>
                </div>
                <div class="contact-item">
                    <h3>Phone</h3>
                    <p>(123) 456-7890</p>
                </div>
            </div>
            
            <div class="contact-form">
                <h3>Send us a message</h3>
                <form action="#" method="post">
                    <div class="form-group">
                        <label for="name">Name</label>
                        <input type="text" id="name" name="name" required>
                    </div>
                    <div class="form-group">
                        <label for="email">Email</label>
                        <input type="email" id="email" name="email" required>
                    </div>
                    <div class="form-group">
                        <label for="message">Message</label>
                        <textarea id="message" name="message" rows="5" required></textarea>
                    </div>
                    <button type="submit" class="submit-button">Send Message</button>
                </form>
            </div>
        </div>
    </section>

    <footer>
        <div class="container">
            <p>&copy; '''
    
    current_year = time.strftime("%Y")
    html_content += f'''{current_year} {business_name}. All rights reserved.</p>
        </div>
    </footer>
</body>
</html>'''

    # Write HTML to file
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

def generate_template_css(template_folder, style):
    """Generate CSS for a website template"""
    css_file = os.path.join(template_folder, 'styles.css')
    
    # Base CSS for all templates
    css_content = '''/* Reset and base styles */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: sans-serif;
    line-height: 1.6;
    color: #333;
}

.container {
    width: 90%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 15px;
}

a {
    text-decoration: none;
}

ul {
    list-style: none;
}

img {
    max-width: 100%;
    height: auto;
}

section {
    padding: 60px 0;
}

h2 {
    margin-bottom: 30px;
    text-align: center;
}

/* Header styles */
header {
    padding: 20px 0;
}

header .container {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
}

.logo {
    margin-right: 20px;
}

.logo img {
    max-height: 60px;
}

header h1 {
    font-size: 1.8rem;
}

nav ul {
    display: flex;
}

nav li {
    margin-left: 20px;
}

/* Hero section */
.hero {
    text-align: center;
    padding: 100px 0;
}

.hero h2 {
    font-size: 2.5rem;
    margin-bottom: 20px;
}

.tagline {
    font-size: 1.2rem;
    margin-bottom: 30px;
}

/* Services section */
.services-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 30px;
    margin-top: 40px;
}

.service-card {
    padding: 30px;
    border-radius: 5px;
    transition: transform 0.3s ease;
}

.service-card:hover {
    transform: translateY(-5px);
}

.service-card h3 {
    margin-bottom: 15px;
}

/* About section */
.about p {
    margin-bottom: 20px;
    max-width: 800px;
    margin-left: auto;
    margin-right: auto;
}

/* Contact section */
.contact-info {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 30px;
    margin-bottom: 50px;
}

.contact-item {
    text-align: center;
}

.contact-item h3 {
    margin-bottom: 10px;
}

.contact-form {
    max-width: 600px;
    margin: 0 auto;
}

.contact-form h3 {
    margin-bottom: 20px;
    text-align: center;
}

.form-group {
    margin-bottom: 20px;
}

.form-group label {
    display: block;
    margin-bottom: 5px;
}

.form-group input,
.form-group textarea {
    width: 100%;
    padding: 10px;
    border-radius: 4px;
    border: 1px solid #ddd;
}

/* Footer styles */
footer {
    padding: 20px 0;
    text-align: center;
}

/* Responsive styles */
@media (max-width: 768px) {
    header .container {
        flex-direction: column;
        text-align: center;
    }
    
    nav {
        margin-top: 20px;
    }
    
    nav ul {
        flex-direction: column;
        align-items: center;
    }
    
    nav li {
        margin: 10px 0;
    }
    
    .hero {
        padding: 60px 0;
    }
    
    .hero h2 {
        font-size: 2rem;
    }
}
'''
    
    # Add style-specific CSS
    if style['name'] == 'modern':
        css_content += f'''
/* Modern template styles */
.modern-template {{
    font-family: {style['font']};
}}

.modern-template header {{
    background-color: white;
    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
}}

.modern-template nav a {{
    color: #333;
    font-weight: 500;
    transition: color 0.3s;
}}

.modern-template nav a:hover {{
    color: {style['primary_color']};
}}

.modern-template .hero {{
    background: linear-gradient(135deg, {style['primary_color']} 0%, {style['secondary_color']} 100%);
    color: white;
}}

.modern-template .cta-button {{
    display: inline-block;
    padding: 12px 30px;
    background-color: white;
    color: {style['primary_color']};
    border-radius: 30px;
    font-weight: bold;
    transition: transform 0.3s, box-shadow 0.3s;
}}

.modern-template .cta-button:hover {{
    transform: translateY(-3px);
    box-shadow: 0 5px 15px rgba(0,0,0,0.2);
}}

.modern-template .service-card {{
    background-color: #f9f9f9;
    box-shadow: 0 5px 15px rgba(0,0,0,0.05);
}}

.modern-template .service-card h3 {{
    color: {style['primary_color']};
}}

.modern-template .submit-button {{
    background-color: {style['primary_color']};
    color: white;
    border: none;
    padding: 12px 30px;
    border-radius: 30px;
    cursor: pointer;
    font-weight: 500;
    transition: background-color 0.3s;
}}

.modern-template .submit-button:hover {{
    background-color: {style['secondary_color']};
}}

.modern-template footer {{
    background-color: #333;
    color: white;
}}
'''
    elif style['name'] == 'elegant':
        css_content += f'''
/* Elegant template styles */
.elegant-template {{
    font-family: {style['font']};
    color: #333;
}}

.elegant-template header {{
    background-color: white;
    border-bottom: 1px solid #eee;
}}

.elegant-template h1, .elegant-template h2, .elegant-template h3 {{
    font-family: {style['font']};
    font-weight: 700;
}}

.elegant-template nav a {{
    color: #333;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-size: 0.9rem;
    transition: color 0.3s;
}}

.elegant-template nav a:hover {{
    color: {style['secondary_color']};
}}

.elegant-template .hero {{
    background-color: #f8f5f0;
    position: relative;
}}

.elegant-template .hero::after {{
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 5px;
    background: {style['secondary_color']};
}}

.elegant-template .cta-button {{
    display: inline-block;
    padding: 12px 30px;
    background-color: {style['secondary_color']};
    color: white;
    border: none;
    font-family: {style['font']};
    text-transform: uppercase;
    letter-spacing: 1px;
    transition: background-color 0.3s;
}}

.elegant-template .cta-button:hover {{
    background-color: {style['primary_color']};
}}

.elegant-template .service-card {{
    background-color: white;
    border: 1px solid #eee;
    padding: 40px 30px;
}}

.elegant-template .service-card h3 {{
    position: relative;
    padding-bottom: 15px;
}}

.elegant-template .service-card h3::after {{
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 50px;
    height: 2px;
    background: {style['secondary_color']};
}}

.elegant-template .submit-button {{
    background-color: {style['secondary_color']};
    color: white;
    border: none;
    padding: 12px 30px;
    font-family: {style['font']};
    text-transform: uppercase;
    letter-spacing: 1px;
    cursor: pointer;
    transition: background-color 0.3s;
}}

.elegant-template .submit-button:hover {{
    background-color: {style['primary_color']};
}}

.elegant-template footer {{
    background-color: {style['primary_color']};
    color: white;
    padding: 40px 0;
}}
'''
    elif style['name'] == 'minimalist':
        css_content += f'''
/* Minimalist template styles */
.minimalist-template {{
    font-family: {style['font']};
    background-color: white;
}}

.minimalist-template header {{
    padding: 30px 0;
}}

.minimalist-template h1, .minimalist-template h2, .minimalist-template h3 {{
    font-weight: 300;
}}

.minimalist-template nav a {{
    color: {style['primary_color']};
    font-size: 0.9rem;
    font-weight: 400;
    transition: opacity 0.3s;
}}

.minimalist-template nav a:hover {{
    opacity: 0.7;
}}

.minimalist-template .hero {{
    background-color: #f8f8f8;
    padding: 150px 0;
}}

.minimalist-template .hero h2 {{
    font-size: 3rem;
    font-weight: 300;
    margin-bottom: 30px;
}}

.minimalist-template .cta-button {{
    display: inline-block;
    padding: 15px 40px;
    background-color: {style['accent_color']};
    color: white;
    border: none;
    font-weight: 400;
    letter-spacing: 1px;
    transition: opacity 0.3s;
}}

.minimalist-template .cta-button:hover {{
    opacity: 0.9;
}}

.minimalist-template section {{
    padding: 100px 0;
}}

.minimalist-template .service-card {{
    background-color: white;
    padding: 40px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}}

.minimalist-template .service-card h3 {{
    font-weight: 400;
    margin-bottom: 20px;
}}

.minimalist-template .contact-item {{
    padding: 30px;
}}

.minimalist-template .form-group input,
.minimalist-template .form-group textarea {{
    border: none;
    background-color: #f8f8f8;
    padding: 15px;
}}

.minimalist-template .submit-button {{
    background-color: {style['primary_color']};
    color: white;
    border: none;
    padding: 15px 40px;
    font-weight: 400;
    letter-spacing: 1px;
    cursor: pointer;
    transition: opacity 0.3s;
}}

.minimalist-template .submit-button:hover {{
    opacity: 0.9;
}}

.minimalist-template footer {{
    padding: 50px 0;
    background-color: {style['primary_color']};
    color: white;
}}
'''
    
    # Write CSS to file
    with open(css_file, 'w', encoding='utf-8') as f:
        f.write(css_content)

@app.route('/clear_data', methods=['POST'])
def clear_data():
    """Clear all scraped data but keep URLs"""
    try:
        if os.path.exists('leads.csv'):
            df = pd.read_csv('leads.csv')
            
            # Keep only URLs and reset other columns
            df = df[['url']].copy()
            
            # Save the cleaned dataframe
            df.to_csv('leads.csv', index=False)
            
            flash('All scraped data cleared successfully', 'success')
        else:
            flash('No data to clear', 'warning')
    except Exception as e:
        flash(f'Error clearing data: {str(e)}', 'danger')
    
    return redirect(url_for('index'))

@app.route('/add_url', methods=['POST'])
def add_url():
    """Add a single URL to the CSV file"""
    url = request.form.get('new_url', '').strip()
    
    if not url:
        flash('URL cannot be empty', 'danger')
        return redirect(url_for('index'))
    
    try:
        # Normalize URL (add https:// if missing)
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Check if file exists, create if not
        if os.path.exists('leads.csv'):
            df = pd.read_csv('leads.csv')
            
            # Check if URL already exists
            if url in df['url'].values:
                flash(f'URL {url} already exists in the list', 'warning')
                return redirect(url_for('index'))
            
            # Add new URL
            new_row = {'url': url}
            for col in df.columns:
                if col != 'url':
                    new_row[col] = None
            
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        else:
            # Create new DataFrame
            df = pd.DataFrame({'url': [url], 'email': None, 'logo': None, 
                              'business_name': None, 'services': None, 'error': None})
        
        # Save the updated DataFrame
        df.to_csv('leads.csv', index=False)
        
        flash(f'URL {url} added successfully', 'success')
    except Exception as e:
        flash(f'Error adding URL: {str(e)}', 'danger')
    
    return redirect(url_for('index'))

@app.route('/download_emails')
def download_emails():
    """Download all emails in a single text file"""
    try:
        # Check if the CSV file exists
        if not os.path.exists('leads.csv'):
            flash('No data to download', 'warning')
            return redirect(url_for('index'))
        
        # Read the CSV
        df = pd.read_csv('leads.csv')
        
        # Create a timestamp for the filename
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f'all_emails_{timestamp}.txt'
        
        # Create a temporary file to store the emails
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"All Emails - Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Count valid emails
            valid_emails = 0
            
            # Process each row
            for index, row in df.iterrows():
                url = row['url'] if pd.notna(row['url']) else 'Unknown URL'
                business_name = row['business_name'] if pd.notna(row['business_name']) else 'Unknown Business'
                email = row['email'] if pd.notna(row['email']) else None
                
                if email:
                    valid_emails += 1
                    f.write(f"{email}\n")
            
            # Add a separator
            f.write("\n\n" + "-" * 50 + "\n\n")
            
            # Add detailed information with context
            f.write("DETAILED INFORMATION:\n\n")
            for index, row in df.iterrows():
                url = row['url'] if pd.notna(row['url']) else 'Unknown URL'
                business_name = row['business_name'] if pd.notna(row['business_name']) else 'Unknown Business'
                email = row['email'] if pd.notna(row['email']) else None
                
                if email:
                    f.write(f"Business: {business_name}\n")
                    f.write(f"Email: {email}\n")
                    f.write(f"Website: {url}\n")
                    f.write("\n")
            
            # Add summary at the end
            f.write(f"\n---\nTotal: {valid_emails} emails out of {len(df)} websites")
        
        # Return the file for download
        return send_file(
            filename,
            mimetype='text/plain',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        flash(f'Error downloading emails: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/template_gallery')
def template_gallery():
    """Show a gallery of all generated templates"""
    try:
        # Find all template zip files
        template_zips = glob.glob('website_templates_*.zip')
        
        # Sort by most recent first
        template_zips.sort(key=os.path.getmtime, reverse=True)
        
        if not template_zips:
            flash('No template packages have been generated yet', 'info')
            return redirect(url_for('index'))
        
        # Use the most recent template package
        latest_zip = template_zips[0]
        
        # Create a temp directory to extract templates
        temp_dir = 'temp_templates'
        
        # Only extract if the directory doesn't exist or is empty
        extract_needed = not os.path.exists(temp_dir) or not os.listdir(temp_dir)
        
        # If directory exists, check if the latest template is already extracted
        latest_zip_basename = os.path.basename(latest_zip)
        latest_template_id = latest_zip_basename.replace('.zip', '')
        
        latest_already_extracted = False
        if os.path.exists(temp_dir):
            template_folders = [d for d in os.listdir(temp_dir) 
                               if os.path.isdir(os.path.join(temp_dir, d)) 
                               and d.startswith('website_templates_')]
            if template_folders:
                # Sort by name (which includes date) to get most recent
                template_folders.sort(reverse=True)
                if template_folders[0] == latest_template_id:
                    latest_already_extracted = True
        
        # If latest isn't extracted, do an extraction
        if not latest_already_extracted:
            os.makedirs(temp_dir, exist_ok=True)
            
            # Clean the temp directory first (but don't remove it)
            for item in os.listdir(temp_dir):
                item_path = os.path.join(temp_dir, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
            
            # Extract the zip file
            with zipfile.ZipFile(latest_zip, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
                print(f"Extracted {latest_zip} to {temp_dir}")
        
        # Get all website folders
        website_folders = []
        
        # First check if there are template_website_* folders (from extraction)
        template_dirs = [d for d in os.listdir(temp_dir) 
                        if os.path.isdir(os.path.join(temp_dir, d)) and 
                        d.startswith('website_templates_')]
        
        if template_dirs:
            # Sort to get the most recent template directory first
            template_dirs.sort(reverse=True)
            latest_dir = template_dirs[0]
            temp_templates_dir = os.path.join(temp_dir, latest_dir)
            
            # Get all websites in the latest template directory
            for folder in os.listdir(temp_templates_dir):
                folder_path = os.path.join(temp_templates_dir, folder)
                if os.path.isdir(folder_path) and folder != '__pycache__':
                    # Get style folders 
                    styles = []
                    for style_folder in os.listdir(folder_path):
                        style_path = os.path.join(folder_path, style_folder)
                        if os.path.isdir(style_path):
                            # Check if there's a logo
                            logo_files = glob.glob(os.path.join(style_path, '*.png')) + \
                                        glob.glob(os.path.join(style_path, '*.jpg')) + \
                                        glob.glob(os.path.join(style_path, '*.jpeg')) + \
                                        glob.glob(os.path.join(style_path, '*.svg'))
                            
                            logo_file = logo_files[0] if logo_files else None
                            
                            styles.append({
                                'name': style_folder,
                                'path': os.path.join(latest_dir, folder, style_folder).replace('\\', '/'),  # Use forward slashes for URLs
                                'logo': os.path.basename(logo_file) if logo_file else None
                            })
                    
                    # Get info from the HTML file if available
                    business_name = folder
                    try:
                        # Try to extract the business name from the HTML
                        if styles:
                            html_path = os.path.join(temp_dir, styles[0]['path'], 'index.html')
                            if os.path.exists(html_path):
                                with open(html_path, 'r', encoding='utf-8') as f:
                                    html_content = f.read()
                                    # Look for the title
                                    title_match = re.search(r'<title>(.*?)</title>', html_content)
                                    if title_match:
                                        business_name = title_match.group(1)
                    except Exception as e:
                        print(f"Error reading HTML title: {str(e)}")
                        # If anything goes wrong, just use the folder name
                        pass
                    
                    website_folders.append({
                        'folder_name': folder,
                        'business_name': business_name,
                        'styles': styles
                    })
        else:
            # Fallback: Look directly in temp_dir for website folders
            for folder in os.listdir(temp_dir):
                folder_path = os.path.join(temp_dir, folder)
                if os.path.isdir(folder_path) and folder != '__pycache__' and not folder.startswith('website_templates_'):
                    # Get style folders 
                    styles = []
                    for style in ['modern', 'elegant', 'minimalist']:
                        style_path = os.path.join(folder_path, style)
                        if os.path.exists(style_path) and os.path.exists(os.path.join(style_path, 'index.html')):
                            # Try to get a screenshot or thumbnail if available
                            thumbnail = None
                            for ext in ['png', 'jpg', 'jpeg']:
                                thumb_path = os.path.join(style_path, f'thumbnail.{ext}')
                                if os.path.exists(thumb_path):
                                    thumbnail = f'thumbnail.{ext}'
                                    break
                    
                    styles.append({
                        'name': style,
                        'path': os.path.join(folder, style, 'index.html').replace('\\', '/'),  # Use forward slashes for URLs
                        'thumbnail': thumbnail
                    })
                    
                    if styles:
                        # Get info from the HTML file if available
                        business_name = folder
                        try:
                            # Try to extract the business name from the HTML
                            html_path = os.path.join(temp_dir, styles[0]['path'], 'index.html')
                            if os.path.exists(html_path):
                                with open(html_path, 'r', encoding='utf-8') as f:
                                    html_content = f.read()
                                    title_match = re.search(r'<title>(.*?)</title>', html_content)
                                    if title_match:
                                        business_name = title_match.group(1)
                        except Exception:
                            pass
                        
                        website_folders.append({
                            'folder_name': folder,
                            'business_name': business_name,
                            'styles': styles
                        })
        
        # Count statistics
        stats = {
            'total_sites': len(website_folders),
            'total_templates': sum(len(site['styles']) for site in website_folders)
        }
        
        # Get generation date from zip file
        generation_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(latest_zip)))
        
        # Sort websites alphabetically
        website_folders.sort(key=lambda x: x['business_name'].lower())
        
        # Check if sites have been deployed
        deployed_urls = {}
        if os.path.exists('deployed_urls.json'):
            with open('deployed_urls.json', 'r') as f:
                deployed_urls = json.load(f)
        
        # Pass deployment status to the template
        return render_template('template_gallery.html', 
                              websites=website_folders, 
                              stats=stats, 
                              generation_date=generation_date,
                              temp_dir=temp_dir,
                              zip_name=os.path.basename(latest_zip),
                              deployed_urls=deployed_urls)
    except Exception as e:
        flash(f'Error displaying template gallery: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/temp_templates/<path:filename>')
def temp_templates(filename):
    """Serve files from temporary template directory"""
    try:
        # Debug info
        print(f"Request for file: {filename}")
        
        temp_dir = 'temp_templates'
        template_styles = ['modern', 'elegant', 'minimalist']
        
        # Normalize path separators
        normalized_filename = filename.replace('/', os.path.sep).replace('\\', os.path.sep)
        direct_path = os.path.join(temp_dir, normalized_filename)
        
        # 1. Try direct path first
        if os.path.exists(direct_path):
            print(f"Serving file via direct path: {direct_path}")
            return send_file(direct_path)
            
        # 2. Check if it's a request for a website_templates folder (with date)
        if 'website_templates_' in filename:
            parts = normalized_filename.split(os.path.sep)
            
            # Split out the template date folder and the rest
            template_date_folder = None
            for i, part in enumerate(parts):
                if part.startswith('website_templates_'):
                    template_date_folder = part
                    break
                    
            if template_date_folder:
                # Find all template folders in temp_templates
                template_folders = [d for d in os.listdir(temp_dir) 
                                    if os.path.isdir(os.path.join(temp_dir, d)) and 
                                    d.startswith('website_templates_')]
                                    
                if template_folders:
                    # Sort by newest first
                    template_folders.sort(reverse=True)
                    
                    # Check if requested folder exists, otherwise use latest
                    if template_date_folder not in template_folders:
                        print(f"Template folder {template_date_folder} not found, using latest: {template_folders[0]}")
                        # Replace requested folder with latest
                        normalized_filename = normalized_filename.replace(template_date_folder, template_folders[0])
                        
                    corrected_path = os.path.join(temp_dir, normalized_filename)
                    if os.path.exists(corrected_path):
                        print(f"Serving via corrected template date path: {corrected_path}")
                        return send_file(corrected_path)
        
        # 3. Split path and check if it's a style path without domain folder
        parts = normalized_filename.split(os.path.sep)
        
        # Check if it's a direct style request (e.g., modern/index.html without domain)
        if len(parts) >= 2 and parts[0] in template_styles and not os.path.exists(direct_path):
            # Find all template folders
            template_folders = [d for d in os.listdir(temp_dir) 
                                if os.path.isdir(os.path.join(temp_dir, d))]
            
            # First look for website_templates_* folders
            date_folders = [d for d in template_folders if d.startswith('website_templates_')]
            
            if date_folders:
                # Sort by newest first
                date_folders.sort(reverse=True)
                latest_date_folder = date_folders[0]
                
                # Look in each domain folder in the latest date folder
                date_folder_path = os.path.join(temp_dir, latest_date_folder)
                domain_folders = [d for d in os.listdir(date_folder_path) 
                                 if os.path.isdir(os.path.join(date_folder_path, d))]
                
                for domain in domain_folders:
                    style_path = os.path.join(date_folder_path, domain, *parts)
                    if os.path.exists(style_path):
                        print(f"Found template in dated domain folder: {style_path}")
                        return send_file(style_path)
            
            # If no date folders or not found in them, look in direct domain folders
            domain_folders = [d for d in template_folders 
                             if os.path.isdir(os.path.join(temp_dir, d)) 
                             and not d.startswith('website_templates_')
                             and d != '__pycache__']
                             
            for domain in domain_folders:
                style_path = os.path.join(temp_dir, domain, *parts)
                if os.path.exists(style_path):
                    print(f"Found template in direct domain folder: {style_path}")
                    return send_file(style_path)
        
        # 4. If it's a domain/style/index.html path
        if len(parts) >= 3:
            domain = parts[0]
            style = parts[1]
            
            # Find all template folders
            template_folders = [d for d in os.listdir(temp_dir) 
                               if os.path.isdir(os.path.join(temp_dir, d))]
            
            # Check date folders first
            date_folders = [d for d in template_folders if d.startswith('website_templates_')]
            
            if date_folders:
                # Sort by newest first
                date_folders.sort(reverse=True)
                
                for date_folder in date_folders:
                    complete_path = os.path.join(temp_dir, date_folder, *parts)
                    if os.path.exists(complete_path):
                        print(f"Found template in date folder: {complete_path}")
                        return send_file(complete_path)
        
        # 5. If still not found, show error page
        error_message = f"""
        <html>
            <head>
                <title>Template Not Found</title>
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            </head>
            <body class="bg-light p-5">
                <div class="container">
                    <div class="row justify-content-center">
                        <div class="col-md-8">
                            <div class="card shadow-sm">
                                <div class="card-body p-4">
                                    <h1 class="text-danger">Template Not Found</h1>
                                    <p>The template file you requested could not be found:</p>
                                    <code class="bg-light p-2 d-block mb-4">{direct_path}</code>
                                    <p>This could be due to:</p>
                                    <ul>
                                        <li>The template has not been generated yet</li>
                                        <li>The template style you requested does not exist</li>
                                        <li>The file path is incorrect</li>
                                    </ul>
                                    <div class="mt-4">
                                        <a href="{{ url_for('generate_templates') }}" class="btn btn-primary">
                                            <i class="bx bx-refresh me-2"></i> Generate New Templates
                                        </a>
                                        <a href="{{ url_for('template_gallery') }}" class="btn btn-outline-primary ms-2">
                                            <i class="bx bx-arrow-back me-2"></i> Back to Gallery
                                        </a>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="container mt-4">
                    <div class="row justify-content-center">
                        <div class="col-md-8">
        """
        
        # List available templates
        available_templates = []
        template_dirs = [d for d in os.listdir(temp_dir) 
                        if os.path.isdir(os.path.join(temp_dir, d)) 
                        and d.startswith('website_templates_')]
        
        if template_dirs:
            # Sort by newest first
            template_dirs.sort(reverse=True)
            latest_dir = template_dirs[0]
            
            error_message += f"""
                <div class="card shadow-sm">
                    <div class="card-header bg-success text-white">
                        <h5 class="mb-0">Available Templates</h5>
                        <p class="text-muted small mb-0">Latest templates from {latest_dir}</p>
                    </div>
                    <div class="card-body">
                        <div class="list-group">
            """
            
            # Add list of available templates
            domains_path = os.path.join(temp_dir, latest_dir)
            if os.path.exists(domains_path):
                domains = [d for d in os.listdir(domains_path) 
                          if os.path.isdir(os.path.join(domains_path, d))]
                
                for domain in sorted(domains):
                    for style in template_styles:
                        template_path = os.path.join(domains_path, domain, style, 'index.html')
                        if os.path.exists(template_path):
                            rel_path = os.path.join(latest_dir, domain, style, 'index.html').replace('\\', '/')
                            error_message += f"""
                                <a href="/temp_templates/{rel_path}" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                                    <span><strong>{domain}</strong> - {style} style</span>
                                    <span class="badge bg-primary rounded-pill">Open</span>
                                </a>
                            """
            
            error_message += """
                        </div>
                    </div>
                </div>
            """
        
        error_message += """
                        </div>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return error_message, 404
        
    except Exception as e:
        error_msg = f"Error serving template file: {str(e)}"
        print(error_msg)
        flash(error_msg, 'danger')
        return redirect(url_for('index'))

@app.route('/view_template')
def view_template():
    """View a specific template with style for a domain"""
    try:
        folder_name = request.args.get('folder_name')
        style = request.args.get('style', 'modern')
        
        if not folder_name:
            flash('No folder name specified', 'warning')
            return redirect(url_for('template_gallery'))
            
        # Get the latest template generation date
        template_zips = glob.glob('website_templates_*.zip')
        template_zips.sort(key=os.path.getmtime, reverse=True)
        if not template_zips:
            flash('No template packages found', 'warning')
            return redirect(url_for('template_gallery'))
            
        generation_date = os.path.basename(template_zips[0]).split('_')[2].split('.')[0]
        
        # Construct the path to the template
        template_path = f"website_templates_{generation_date}/{folder_name}/{style}/index.html"
        
        return redirect(url_for('temp_templates', filename=template_path))
    except Exception as e:
        flash(f'Error viewing template: {str(e)}', 'danger')
        return redirect(url_for('template_gallery'))

@app.route('/view_all_templates')
def view_all_templates():
    """View a page showing all templates for a specific domain"""
    try:
        folder_name = request.args.get('folder_name')
        
        if not folder_name:
            flash('No folder name specified', 'warning')
            return redirect(url_for('template_gallery'))
            
        temp_dir = 'temp_templates'
        folder_path = os.path.join(temp_dir, folder_name)
        styles = []
        
        # First try direct path
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            # Get all styles available for this domain
            template_styles = ['modern', 'elegant', 'minimalist']
            
            for style in template_styles:
                style_path = os.path.join(folder_path, style)
                if os.path.exists(style_path) and os.path.exists(os.path.join(style_path, 'index.html')):
                    # Try to get a screenshot or thumbnail if available
                    thumbnail = None
                    for ext in ['png', 'jpg', 'jpeg']:
                        thumb_path = os.path.join(style_path, f'thumbnail.{ext}')
                        if os.path.exists(thumb_path):
                            thumbnail = f'thumbnail.{ext}'
                            break
                    
                    styles.append({
                        'name': style,
                        'path': os.path.join(folder_name, style, 'index.html').replace('\\', '/'),  # Use forward slashes for URLs
                        'thumbnail': thumbnail
                    })
        else:
            # If direct path doesn't exist, check in website_templates_* directories
            template_dirs = [d for d in os.listdir(temp_dir) 
                            if os.path.isdir(os.path.join(temp_dir, d)) and 
                            d.startswith('website_templates_')]
            
            if template_dirs:
                # Sort to get the most recent template directory first
                template_dirs.sort(reverse=True)
                template_styles = ['modern', 'elegant', 'minimalist']
                
                for template_dir in template_dirs:
                    template_site_path = os.path.join(temp_dir, template_dir, folder_name)
                    if os.path.exists(template_site_path) and os.path.isdir(template_site_path):
                        for style in template_styles:
                            style_path = os.path.join(template_site_path, style)
                            if os.path.exists(style_path) and os.path.exists(os.path.join(style_path, 'index.html')):
                                # Try to get a screenshot or thumbnail if available
                                thumbnail = None
                                for ext in ['png', 'jpg', 'jpeg']:
                                    thumb_path = os.path.join(style_path, f'thumbnail.{ext}')
                                    if os.path.exists(thumb_path):
                                        thumbnail = f'thumbnail.{ext}'
                                        break
                                
                                styles.append({
                                    'name': style,
                                    'path': os.path.join(template_dir, folder_name, style, 'index.html').replace('\\', '/'),  # Use forward slashes for URLs
                                    'thumbnail': thumbnail
                                })
                        
                        # If we found templates in this directory, don't check the others
                        if styles:
                            break
        
        if not styles:
            flash(f'Templates for {folder_name} not found', 'warning')
            return redirect(url_for('template_gallery'))
                
        # Get business name from HTML if available
        business_name = folder_name
        if styles:
            first_style = styles[0]
            html_path = os.path.join(temp_dir, first_style['path'])
            try:
                # Try to extract the business name from the HTML
                if styles:
                    with open(html_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                        # Look for the title
                        title_match = re.search(r'<title>(.*?)</title>', html_content)
                        if title_match:
                            business_name = title_match.group(1)
            except Exception as e:
                print(f"Error reading HTML for business name: {str(e)}")
                # If anything goes wrong, just use the folder name
                pass
                
        # Get the generation date
        template_zips = glob.glob('website_templates_*.zip')
        template_zips.sort(key=os.path.getmtime, reverse=True)
        if template_zips:
            generation_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(template_zips[0])))
        else:
            generation_date = time.strftime('%Y-%m-%d %H:%M:%S')
        
        return render_template('template_details.html',
                              folder_name=folder_name,
                              business_name=business_name,
                              styles=styles,
                              generation_date=generation_date)
    except Exception as e:
        flash(f'Error viewing templates: {str(e)}', 'danger')
        return redirect(url_for('template_gallery'))

@app.route('/download_templates/<business_name>')
def download_templates(business_name):
    """Download all templates for a specific business"""
    try:
        # Find the business folder in temp_templates
        temp_dir = 'temp_templates'
        business_folder = None
        
        # First try an exact match
        if os.path.exists(os.path.join(temp_dir, business_name)):
            business_folder = business_name
        else:
            # If not found, try to find a match by business name
            for folder in os.listdir(temp_dir):
                folder_path = os.path.join(temp_dir, folder)
                if os.path.isdir(folder_path) and folder != '__pycache__':
                    # Check if there's an index.html file to read the title
                    for style in ['modern', 'elegant', 'minimalist']:
                        html_path = os.path.join(folder_path, style, 'index.html')
                        if os.path.exists(html_path):
                            try:
                                with open(html_path, 'r', encoding='utf-8') as f:
                                    html_content = f.read()
                                    title_match = re.search(r'<title>(.*?)</title>', html_content)
                                    if title_match and title_match.group(1) == business_name:
                                        business_folder = folder
                                        break
                            except Exception:
                                pass
                    if business_folder:
                        break
        
        if not business_folder:
            flash(f'Templates for {business_name} not found', 'warning')
            return redirect(url_for('template_gallery'))
        
        # Create a zip file with all templates for this business
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        zip_filename = f'templates_{secure_filename(business_name)}_{timestamp}.zip'
        
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            business_path = os.path.join(temp_dir, business_folder)
            for root, dirs, files in os.walk(business_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)
        
        return send_file(
            zip_filename,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )
        
    except Exception as e:
        flash(f'Error downloading templates: {str(e)}', 'danger')
        return redirect(url_for('template_gallery'))

def get_next_site_id():
    """Get the next available site ID for hosting"""
    
    # Path to the counter file
    counter_file = 'site_counter.txt'
    
    # Default starting ID
    current_id = STARTING_SITE_ID
    
    # Read current ID if file exists
    if os.path.exists(counter_file):
        with open(counter_file, 'r') as f:
            try:
                current_id = int(f.read().strip())
            except:
                # If file is corrupted, start with default
                pass
    
    # Increment the ID
    next_id = current_id + 1
    
    # Save the new ID
    with open(counter_file, 'w') as f:
        f.write(str(next_id))
    
    # Format the ID with prefix
    formatted_id = f"ljif{next_id}"
    
    return formatted_id

@app.route('/deploy_to_server')
def deploy_to_server():
    """Deploy all templates to the FTP server defined in the config."""
    try:
        # Check for the latest folder counter from the FTP server
        from deploy_to_server import deploy_templates
        
        # Execute the deployment
        success, result = deploy_templates()
        
        # Record deployment in logs
        deployment_log_file = 'deployment_logs.json'
        
        # Read existing logs
        if os.path.exists(deployment_log_file):
            try:
                with open(deployment_log_file, 'r') as f:
                    deployment_logs = json.load(f)
            except:
                deployment_logs = []
        else:
            deployment_logs = []
        
        # Add new deployment log
        deployment_logs.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'success': success,
            'result': result if isinstance(result, str) else str(result),
            'target_directory': FTP_CONFIG['base_path'],
            'server': FTP_CONFIG['host']
        })
        
        # Save logs (keep only last 50 entries)
        with open(deployment_log_file, 'w') as f:
            json.dump(deployment_logs[-50:], f, indent=2)
        
        if success:
            # Store deployed URLs in session
            session['deployed_urls'] = result
            
            try:
                # Now automatically update template URLs in leads.csv
                update_template_urls()
                flash('Templates deployed successfully! Leads CSV has been updated with template URLs.', 'success')
            except Exception as e:
                logging.error(f"Error updating template URLs: {str(e)}")
                flash('Templates deployed successfully, but failed to update leads CSV. Please click "Update Template URLs" manually.', 'warning')
        else:
            flash(f'Deployment failed: {result}', 'danger')
        
        return redirect(url_for('template_gallery'))
        
    except ImportError:
        error_msg = "Deployment module not found. Check if deploy_to_server.py exists."
        logging.error(error_msg)
        flash(error_msg, 'danger')
        return redirect(url_for('template_gallery'))
    except Exception as e:
        error_msg = f"Error deploying to server: {str(e)}"
        logging.error(error_msg)
        flash(error_msg, 'danger')
        return redirect(url_for('template_gallery'))

@app.route('/test_ftp_connection')
def test_ftp_connection():
    """Test the FTP connection to help troubleshoot deployment issues"""
    try:
        # Log the FTP connection attempt
        print("Testing FTP connection...")
        logging.info("Testing FTP connection...")
        
        # Fix FTP host if it includes protocol
        ftp_host = FTP_CONFIG['host']
        if ftp_host.startswith('ftp://'):
            ftp_host = ftp_host[6:]  # Remove ftp. prefix
        
        try:
            import ftplib
            ftp = ftplib.FTP()
            
            # Connect to server
            print(f"Connecting to FTP server {ftp_host}:{FTP_CONFIG['port']}...")
            ftp.connect(ftp_host, FTP_CONFIG['port'])
            print("FTP server connection established")
            
            # Try to login with the provided credentials
            print(f"Attempting login with username: {FTP_CONFIG['username']}")
            ftp.login(FTP_CONFIG['username'], FTP_CONFIG['password'])
            print("Login successful")
            
            # Print current directory
            current_dir = ftp.pwd()
            print(f"Current directory: {current_dir}")
            
            # List directory contents
            print("Directory listing:")
            files = []
            ftp.dir(files.append)
            for file in files[:10]:  # Show first 10 files
                print(f"  {file}")
            
            # Try to change to the target directory
            target_dir = FTP_CONFIG['base_path']
            try:
                print(f"Changing to directory: {target_dir}")
                ftp.cwd(target_dir)
                print(f"Successfully changed to: {ftp.pwd()}")
                
                # List contents of the target directory
                print(f"Contents of {target_dir}:")
                target_files = []
                ftp.dir(target_files.append)
                for file in target_files[:10]:  # Show first 10 files
                    print(f"  {file}")
            except Exception as e:
                print(f"Error changing to target directory: {str(e)}")
            
            # Close connection
            ftp.quit()
            print("FTP connection closed successfully")
            
            # Return success message
            return """
            <html>
                <head>
                    <title>FTP Test Success</title>
                    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                </head>
                <body class="bg-light p-5">
                    <div class="container">
                        <div class="card shadow">
                            <div class="card-header bg-success text-white">
                                <h5 class="mb-0">FTP Connection Successful!</h5>
                            </div>
                            <div class="card-body">
                                <p>Successfully connected to the FTP server with the provided credentials.</p>
                                <p>Check the server logs for more detailed information.</p>
                                <a href="{{ url_for('generate_templates') }}" class="btn btn-primary">
                                    <i class="bx bx-refresh me-2"></i> Generate New Templates
                                </a>
                                <a href="{{ url_for('template_gallery') }}" class="btn btn-outline-primary ms-2">
                                    <i class="bx bx-arrow-back me-2"></i> Back to Gallery
                                </a>
                            </div>
                        </div>
                    </div>
                </body>
            </html>
            """.format(url_for('template_gallery'))
        
        except Exception as e:
            # Show detailed error information
            error_msg = str(e)
            print(f"FTP connection error: {error_msg}")
            logging.error(f"FTP connection error: {error_msg}")
            
            # Return error message
            return """
            <html>
                <head>
                    <title>FTP Test Failed</title>
                    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                </head>
                <body class="bg-light p-5">
                    <div class="container">
                        <div class="card shadow">
                            <div class="card-header bg-danger text-white">
                                <h5 class="mb-0">FTP Connection Failed</h5>
                            </div>
                            <div class="card-body">
                                <p>Failed to connect to the FTP server with the provided credentials.</p>
                                <div class="alert alert-danger">
                                    <strong>Error:</strong> {}
                                </div>
                                <h6 class="mt-4">Troubleshooting Tips:</h6>
                                <ul>
                                    <li>Check the hostname/IP address in config.py</li>
                                    <li>Verify the FTP username and password</li>
                                    <li>Ensure the FTP port is correct (usually 21)</li>
                                    <li>Check if the FTP server is accessible from your network</li>
                                    <li>Contact your hosting provider for the correct FTP credentials</li>
                                </ul>
                                <div class="mt-4">
                                    <a href="{{ url_for('generate_templates') }}" class="btn btn-primary">
                                        <i class="bx bx-refresh me-2"></i> Generate New Templates
                                    </a>
                                    <a href="{{ url_for('template_gallery') }}" class="btn btn-outline-primary ms-2">
                                        <i class="bx bx-arrow-back me-2"></i> Back to Gallery
                                    </a>
                                </div>
                            </div>
                        </div>
                    </div>
                </body>
            </html>
            """.format(error_msg, url_for('template_gallery'))
            
    except Exception as e:
        # Handle any other exceptions
        error_msg = f"Error testing FTP connection: {str(e)}"
        print(error_msg)
        logging.exception(error_msg)
        return f"<h1>Error:</h1><pre>{error_msg}</pre><a href='{url_for('template_gallery')}'>Return to Gallery</a>"

@app.route('/deployment_logs')
def deployment_logs():
    """Display deployment history and logs"""
    try:
        # Check if log file exists
        deployment_log_file = 'deployment_logs.json'
        if not os.path.exists(deployment_log_file):
            # Create empty log file
            with open(deployment_log_file, 'w') as f:
                json.dump([], f)
        
        # Read deployment logs
        with open(deployment_log_file, 'r') as f:
            try:
                deployment_history = json.load(f)
            except json.JSONDecodeError:
                deployment_history = []
        
        # Get FTP configuration for display (hide password)
        ftp_config = FTP_CONFIG.copy()
        if 'password' in ftp_config:
            ftp_config['password'] = '********'
        
        return render_template(
            'deployment_logs.html', 
            deployment_history=deployment_history,
            ftp_config=ftp_config
        )
    except Exception as e:
        error_msg = f"Error loading deployment logs: {str(e)}"
        logging.error(error_msg)
        flash(error_msg, 'danger')
        return redirect(url_for('template_gallery'))

@app.route('/subdomain_manager', methods=['GET', 'POST'])
def subdomain_manager():
    """Manage subdomain mappings for templates"""
    # File to store subdomain mappings
    subdomain_file = 'subdomain_mappings.json'
    
    # Initialize empty mappings if file doesn't exist
    if not os.path.exists(subdomain_file):
        with open(subdomain_file, 'w') as f:
            json.dump([], f)
    
    # Load existing mappings
    with open(subdomain_file, 'r') as f:
        try:
            subdomain_mappings = json.load(f)
        except json.JSONDecodeError:
            subdomain_mappings = []
    
    # Get all template folders
    temp_dir = 'temp_templates'
    website_folders = []
    if os.path.exists(temp_dir):
        # Get template timestamp folders
        timestamp_folders = [d for d in os.listdir(temp_dir) 
                           if os.path.isdir(os.path.join(temp_dir, d))]
        
        for timestamp_folder in timestamp_folders:
            timestamp_path = os.path.join(temp_dir, timestamp_folder)
            # Get website folders inside timestamp folder
            websites = [d for d in os.listdir(timestamp_path) 
                       if os.path.isdir(os.path.join(timestamp_path, d))]
            
            for website in websites:
                website_path = os.path.join(timestamp_path, website)
                # Get style folders 
                styles = [d for d in os.listdir(website_path) 
                         if os.path.isdir(os.path.join(website_path, d))]
                
                website_folders.append({
                    'timestamp_folder': timestamp_folder,
                    'website': website,
                    'styles': styles,
                    'path': f"{timestamp_folder}/{website}"
                })
    
    # Handle form submission to add new subdomain mapping
    if request.method == 'POST':
        subdomain = request.form.get('subdomain')
        website_path = request.form.get('website_path')
        style = request.form.get('style')
        active = request.form.get('active') == 'on'
        
        if subdomain and website_path and style:
            # Check if subdomain already exists
            existing_index = next((i for i, mapping in enumerate(subdomain_mappings) 
                                if mapping['subdomain'] == subdomain), None)
            
            # Get base domain from config
            from config import DOMAIN_CONFIG, FTP_CONFIG
            base_domain = DOMAIN_CONFIG.get('base_domain', 'jede-website.de')
            
            new_mapping = {
                'subdomain': subdomain,
                'website_path': website_path,
                'style': style,
                'date_added': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'active': active,
                'document_root': f"{FTP_CONFIG['base_path']}/{website_path}/{style}",
                'url': f"https://{subdomain}.{base_domain}"
            }
            
            if existing_index is not None:
                # Update existing mapping
                subdomain_mappings[existing_index] = new_mapping
                flash(f'Updated subdomain mapping for {subdomain}.{base_domain}', 'success')
            else:
                # Add new mapping
                subdomain_mappings.append(new_mapping)
                flash(f'Added new subdomain mapping for {subdomain}.{base_domain}', 'success')
            
            # Save updated mappings
            with open(subdomain_file, 'w') as f:
                json.dump(subdomain_mappings, f, indent=2)
    
    # Handle deletion of a mapping
    delete_id = request.args.get('delete')
    if delete_id and delete_id.isdigit():
        delete_index = int(delete_id)
        if 0 <= delete_index < len(subdomain_mappings):
            deleted = subdomain_mappings.pop(delete_index)
            with open(subdomain_file, 'w') as f:
                json.dump(subdomain_mappings, f, indent=2)
            from config import DOMAIN_CONFIG
            base_domain = DOMAIN_CONFIG.get('base_domain', 'jede-website.de')
            flash(f'Deleted subdomain mapping for {deleted["subdomain"]}.{base_domain}', 'success')
    
    # Get server details for display
    try:
        from config import DOMAIN_CONFIG, FTP_CONFIG
        server_info = {
            'host': FTP_CONFIG['host'].replace('ftp.', ''), # Remove ftp. prefix for base domain
            'base_domain': DOMAIN_CONFIG.get('base_domain', 'jede-website.de'),
            'base_path': FTP_CONFIG['base_path'],
            'access_url': DOMAIN_CONFIG.get('access_url', f"https://www.{DOMAIN_CONFIG.get('base_domain', 'jede-website.de')}/templates/")
        }
    except ImportError:
        # Default if config not found
        server_info = {
            'host': FTP_CONFIG['host'].replace('ftp.', ''),
            'base_domain': 'jede-website.de',
            'base_path': FTP_CONFIG['base_path'],
            'access_url': 'https://www.jede-website.de/templates/'
        }
    
    return render_template(
        'subdomain_manager.html',
        subdomain_mappings=subdomain_mappings,
        website_folders=website_folders,
        server_info=server_info
    )

# Add email routes
@app.route('/email_campaign')
def email_campaign_page():
    """Email campaign dashboard page"""
    # Check if history file exists
    history_file = 'email_campaign_history.json'
    campaign_history = []
    
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                campaign_history = json.load(f)
        except:
            pass
    
    # Check if leads.csv exists and get stats
    csv_stats = {
        'total_leads': 0,
        'stage1': 0,
        'stage2': 0,
        'stage3': 0,
        'completed': 0
    }
    
    if os.path.exists('leads.csv'):
        try:
            df = pd.read_csv('leads.csv')
            
            # Count stages if they exist
            if 'stage' in df.columns:
                csv_stats['stage1'] = len(df[df['stage'] == 1])
                csv_stats['stage2'] = len(df[df['stage'] == 2])
                csv_stats['stage3'] = len(df[df['stage'] == 3])
                
                # Leads that completed all stages (no next_send date)
                if 'next_send' in df.columns:
                    csv_stats['completed'] = len(df[(df['stage'] == 3) & (df['next_send'].isna() | (df['next_send'] == ''))])
        except Exception as e:
            logging.error(f"Error reading leads.csv: {str(e)}")
    
    # Check email configuration
    try:
        email_test_results = email_sender.test_email_config()
        valid_accounts = [t for t in email_test_results if t["success"]]
        invalid_accounts = [t for t in email_test_results if not t["success"]]
    except Exception as e:
        valid_accounts = []
        invalid_accounts = []
        logging.error(f"Error testing email configuration: {str(e)}")
    
    # Get current progress if a campaign is running
    progress = None
    
    return render_template(
        'email_campaign.html',
        campaign_history=campaign_history,
        csv_stats=csv_stats,
        email_domains=email_sender.EMAIL_DOMAINS,
        progress=progress,
        valid_accounts=len(valid_accounts),
        invalid_accounts=len(invalid_accounts)
    )

@app.route('/email_status')
def email_status():
    """Get real-time status of the email campaign"""
    progress = None
    return jsonify(progress)

@app.route('/run_email_campaign', methods=['POST'])
def run_email_campaign_route():
    """Run the email campaign"""
    try:
        # Get specific stage if requested
        stage = request.form.get('stage', None)
        if stage and stage.isdigit():
            stage = int(stage)
        else:
            stage = None
        
        # Get specific sender account if requested
        sender_index = request.form.get('sender_index', None)
        if sender_index and sender_index.isdigit():
            sender_index = int(sender_index)
        else:
            sender_index = None
        
        # Check if already running
        if email_sender.get_sending_progress()["is_running"]:
            flash('Email campaign is already running', 'warning')
            return redirect(url_for('email_campaign_page'))
        
        # Run the campaign in a background thread
        def run_campaign_task():
            try:
                success, result = email_sender.run_email_campaign(stage, sender_index)
                if not success:
                    logging.error(f"Email campaign failed: {result}")
            except Exception as e:
                logging.error(f"Error in email campaign thread: {str(e)}")
        
        # Start the campaign in a background thread
        thread = threading.Thread(target=run_campaign_task)
        thread.daemon = True
        thread.start()
        
        flash('Email campaign started. Check the progress in real-time below.', 'success')
    except Exception as e:
        flash(f'Error starting email campaign: {str(e)}', 'danger')
    
    return redirect(url_for('email_campaign_page'))

@app.route('/test_email', methods=['POST'])
def test_email():
    """Send a test email"""
    try:
        recipient = request.form.get('test_email', '')
        sender_index = request.form.get('sender_index', '')
        
        if not recipient:
            flash('Please provide a valid email address', 'danger')
            return redirect(url_for('email_campaign_page'))
        
        # Use specific sender if provided
        if sender_index and sender_index.isdigit():
            sender_idx = int(sender_index)
            if 0 <= sender_idx < len(email_sender.EMAIL_DOMAINS):
                # Get selected domain info for display
                selected_sender = email_sender.EMAIL_DOMAINS[sender_idx]["username"]
                selected_host = email_sender.EMAIL_DOMAINS[sender_idx]["smtp_host"]
                
                # Use our new direct test email function with specific sender
                success, message = email_sender.send_test_email(
                    recipient,
                    f"Test message sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} from {selected_sender} using {selected_host}"
                )
                
                if success:
                    flash(f'Test email sent successfully from {selected_sender} to {recipient}. Please check your inbox AND spam folder.', 'success')
                else:
                    flash(f'Failed to send test email from {selected_sender}: {message}', 'danger')
                return redirect(url_for('email_campaign_page'))
        
        # If no specific sender or invalid index, try all accounts 
        success, message = email_sender.send_test_email(
            recipient,
            f"Test message sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        if success:
            flash(f'Test email sent successfully to {recipient}. Please check your inbox (and spam folder).', 'success')
        else:
            flash(f'Failed to send test email: {message}. Try selecting a specific sender account.', 'danger')
    except Exception as e:
        flash(f'Error sending test email: {str(e)}', 'danger')
    
    return redirect(url_for('email_campaign_page'))

@app.route('/direct_test_email', methods=['POST'])
def direct_test_email():
    """Send a direct test email bypassing normal path"""
    try:
        recipient = request.form.get('test_email', '')
        custom_message = request.form.get('custom_message', 'This is a direct test email')
        sender_index = request.form.get('sender_index', '')
        
        if not recipient:
            flash('Please provide a valid email address', 'danger')
            return redirect(url_for('email_campaign_page'))
        
        # Use specific sender if provided
        if sender_index and sender_index.isdigit():
            sender_idx = int(sender_index)
            if 0 <= sender_idx < len(email_sender.EMAIL_DOMAINS):
                selected_domain = email_sender.EMAIL_DOMAINS[sender_idx]
                
                # Create message
                msg = MIMEMultipart('alternative')
                from_name = "Website Design Team TEST"
                msg['From'] = f"{from_name} <{selected_domain['username']}>"
                msg['To'] = recipient
                msg['Subject'] = "TEST EMAIL - Direct Sender Test"
                msg['Message-ID'] = f"<test{int(time.time())}@{selected_domain['username'].split('@')[1]}>"
                msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')
                
                # Simple content
                text_content = f"""DIRECT TEST EMAIL from {selected_domain['username']} using {selected_domain['smtp_host']}
                
Time sent: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Custom message: {custom_message}

If you received this, please respond to confirm.
"""
                html_content = f"""
                <html>
                <head></head>
                <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd;">
                        <h2 style="color: #4CAF50;">DIRECT TEST EMAIL</h2>
                        <p><strong>From:</strong> {selected_domain['username']}</p>
                        <p><strong>Server:</strong> {selected_domain['smtp_host']}</p>
                        <p><strong>Time sent:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p><strong>Custom message:</strong> {custom_message}</p>
                        <p>If you received this, please respond to confirm.</p>
                    </div>
                </body>
                </html>
                """
                
                msg.attach(MIMEText(text_content, 'plain'))
                msg.attach(MIMEText(html_content, 'html'))
                
                try:
                    # Connect and send
                    if selected_domain.get("use_ssl", False):
                        server = smtplib.SMTP_SSL(selected_domain["smtp_host"], selected_domain["port"], timeout=30)
                    else:
                        server = smtplib.SMTP(selected_domain["smtp_host"], selected_domain["port"], timeout=30)
                        server.starttls()
                        
                    server.login(selected_domain["username"], selected_domain["password"])
                    server.send_message(msg)
                    server.quit()
                    
                    flash(f'DIRECT test email sent from {selected_domain["username"]} to {recipient}. Check inbox AND spam folder immediately.', 'success')
                    return redirect(url_for('email_campaign_page'))
                except Exception as e:
                    flash(f'Failed to send direct test email from {selected_domain["username"]}: {str(e)}', 'danger')
                    return redirect(url_for('email_campaign_page'))
        
        # Try default method if no specific sender
        success, message = email_sender.send_test_email(
            recipient,
            custom_message
        )
        
        if success:
            flash(f'DIRECT test email sent to {recipient}. Check inbox AND spam folder immediately.', 'success')
        else:
            flash(f'Failed to send direct test email: {message}. Try selecting a specific sender.', 'danger')
    except Exception as e:
        flash(f'Error sending direct test email: {str(e)}', 'danger')
    
    return redirect(url_for('email_campaign_page'))

@app.route('/update_template_urls')
def update_template_urls():
    """Update template URLs in leads.csv based on the latest folder counter"""
    try:
        # Get the current folder counter
        main_folder_counter = 1
        try:
            if os.path.exists('ftp_folder_counter.txt'):
                with open('ftp_folder_counter.txt', 'r') as f:
                    content = f.read().strip()
                    if content:
                        main_folder_counter = int(content)
                logging.info(f"Using main folder counter: {main_folder_counter}")
        except Exception as e:
            logging.error(f"Error reading folder counter: {str(e)}")
        
        # Load domain to FTP mapping if it exists
        domain_mapping = {}
        try:
            if os.path.exists('domain_to_ftp_mapping.json'):
                with open('domain_to_ftp_mapping.json', 'r') as f:
                    domain_mapping = json.load(f)
                    logging.info(f"Loaded domain mapping with {len(domain_mapping)} entries")
        except Exception as e:
            logging.error(f"Error loading domain mapping: {str(e)}")
        
        # Read leads.csv
        if not os.path.exists('leads.csv'):
            flash('No leads.csv file found', 'warning')
            return redirect(url_for('index'))
        
        df = pd.read_csv('leads.csv')
        
        # Ensure required columns exist
        required_columns = ['template_url', 'elegant_url', 'minimalist_url', 'modern_url']
        for col in required_columns:
            if col not in df.columns:
                df[col] = ""
        
        # Track which URLs were updated
        updated_count = 0
        
        # For each row in the CSV
        for idx, row in df.iterrows():
            # Skip rows without a URL
            if not pd.notna(row.get('url')) or not row['url']:
                continue
                
            # Extract domain from URL
            url = row['url'].strip()
            domain = None
            
            try:
                from urllib.parse import urlparse
                url_parts = urlparse(url)
                if url_parts.netloc:
                    domain = url_parts.netloc.lower()
                    # Remove www. if present
                    if domain.startswith('www.'):
                        domain = domain[4:]
                else:
                    # Try to extract domain from non-standard URL format
                    domain_parts = url.split('//')
                    if len(domain_parts) > 1:
                        domain = domain_parts[1].split('/')[0].lower()
            except Exception as e:
                logging.error(f"Error parsing URL {url}: {str(e)}")
                continue
                
            if not domain:
                continue
                
            # Clean domain for folder name
            clean_domain = domain.split('.')[0]
            
            # Check if we have a mapping for this domain
            inner_folder = clean_domain
            if domain in domain_mapping:
                mapped_info = domain_mapping[domain]
                inner_folder = mapped_info.get('inner_folder', clean_domain)
                main_folder = mapped_info.get('main_folder', f"{main_folder_counter:06d}")
            else:
                # If no mapping exists, use the current folder counter
                main_folder = f"{main_folder_counter:06d}"
                
                # Add to domain mapping for future use
                domain_mapping[domain] = {
                    'main_folder': main_folder,
                    'inner_folder': inner_folder,
                    'ftp_name': domain
                }
            
            # Generate URLs for each template style
            urls = {
                'template_url': f"https://jede-website-info.de/{main_folder}/{inner_folder}/elegant/index.html",
                'elegant_url': f"https://jede-website-info.de/{main_folder}/{inner_folder}/elegant/index.html",
                'minimalist_url': f"https://jede-website-info.de/{main_folder}/{inner_folder}/minimalist/index.html",
                'modern_url': f"https://jede-website-info.de/{main_folder}/{inner_folder}/modern/index.html"
            }
            
            # Update URLs if they've changed
            changed = False
            for col, url_value in urls.items():
                if not pd.notna(row.get(col)) or row[col] != url_value:
                    df.at[idx, col] = url_value
                    changed = True
            
            if changed:
                updated_count += 1
        
        # Save updated domain mapping
        try:
            with open('domain_to_ftp_mapping.json', 'w') as f:
                json.dump(domain_mapping, f, indent=2)
                logging.info(f"Saved domain mapping with {len(domain_mapping)} entries")
        except Exception as e:
            logging.error(f"Error saving domain mapping: {str(e)}")
        
        # Save the updated CSV
        df.to_csv('leads.csv', index=False)
        
        if updated_count > 0:
            flash(f'Updated template URLs for {updated_count} leads', 'success')
        else:
            flash('No template URLs needed updating', 'info')
            
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'Error updating template URLs: {str(e)}', 'danger')
        logging.error(f"Error updating template URLs: {str(e)}")
        return redirect(url_for('index'))

@app.route('/quick_update_template_urls')
def quick_update_template_urls():
    """Alias for update_template_urls for backward compatibility"""
    return update_template_urls()

@app.route('/email-sender', methods=['GET', 'POST'])
def email_sender_page():
    # Import logic from email_sender.py, but inline here for single app
    import pandas as pd
    from flask import request, render_template, jsonify, redirect, url_for, flash
    import logging
    from datetime import datetime
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    import ssl

    def load_leads():
        try:
            df = pd.read_csv('leads.csv')
            return df.to_dict('records')
        except Exception as e:
            logging.error(f"Error loading leads: {str(e)}")
            return []

    if request.method == 'POST':
        # Handle sending emails
        sender_email = request.form.get('sender_email')
        sender_password = request.form.get('sender_password')
        subject = request.form.get('subject')
        selected_leads = request.form.getlist('selected_leads')
        leads = load_leads()
        results = []
        for lead_index in selected_leads:
            lead_index = int(lead_index)
            if lead_index >= len(leads):
                continue
            lead = leads[lead_index]
            html_content = f"""
            <html><body><h2>Hello {lead['business_name']}</h2><p>Templates:</p>
            <ul>
            <li><a href='{lead['elegant_url']}'>Elegant</a></li>
            <li><a href='{lead['minimalist_url']}'>Minimalist</a></li>
            <li><a href='{lead['modern_url']}'>Modern</a></li>
            </ul></body></html>"""
            # SMTP logic (Strato/Hostinger)
            if any(domain in sender_email for domain in [
                'mail-jede-website.de', 'jede-website-mail.de', 'jede-website-email.de', 'email-jede-website.de']):
                smtp_server = 'smtp.strato.de'
            else:
                smtp_server = 'smtp.hostinger.com'
            port = 465
            try:
                server = smtplib.SMTP_SSL(smtp_server, port, context=ssl.create_default_context())
                server.login(sender_email, sender_password)
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = sender_email
                msg['To'] = lead['email']
                msg.attach(MIMEText(html_content, 'html'))
                server.sendmail(sender_email, lead['email'], msg.as_string())
                server.quit()
                results.append({'email': lead['email'], 'business_name': lead['business_name'], 'success': True, 'message': 'Sent'})
            except Exception as e:
                results.append({'email': lead['email'], 'business_name': lead['business_name'], 'success': False, 'message': str(e)})
        return render_template('results.html', results=results)
    # GET: render sender UI
    leads = load_leads()
    return render_template('email_sender.html', leads=leads)

# For AJAX preview
@app.route('/email-sender/preview', methods=['POST'])
def email_sender_preview():
    import pandas as pd
    from flask import request, jsonify
    leads = pd.read_csv('leads.csv').to_dict('records')
    lead_index = int(request.form.get('lead_index'))
    lead = leads[lead_index]
    preview_data = {
        'recipient': lead['email'],
        'business_name': lead['business_name'],
        'elegant_url': lead['elegant_url'],
        'minimalist_url': lead['minimalist_url'],
        'modern_url': lead['modern_url'],
        'logo': lead.get('logo', ''),
        'sender_email': request.form.get('sender_email'),
        'subject': request.form.get('subject')
    }
    return jsonify(preview_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
