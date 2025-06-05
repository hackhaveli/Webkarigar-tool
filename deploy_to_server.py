import ftplib
import os
from io import BytesIO
import logging
import sys
import time
from config import FTP_CONFIG

def test_ftp_connection():
    """Test FTP connection with various credential formats"""
    print("FTP Connection Test")
    print("-" * 60)
    print(f"Host: {FTP_CONFIG['host']}")
    print(f"Username: {FTP_CONFIG['username']}")
    print(f"Password: {'*' * len(FTP_CONFIG['password'])}")
    print(f"Port: {FTP_CONFIG['port']}")
    print(f"Base Path: {FTP_CONFIG['base_path']}")
    print("-" * 60)
    
    # Fix FTP host if it includes protocol
    ftp_host = FTP_CONFIG['host']
    if ftp_host.startswith('ftp://'):
        ftp_host = ftp_host[6:]  # Remove 'ftp://' prefix
    
    # Connection details
    username = FTP_CONFIG['username']
    password = FTP_CONFIG['password']
    port = FTP_CONFIG['port']
    
    try:
        # Connect to server
        print(f"Connecting to FTP server {ftp_host}:{port}...")
        ftp = ftplib.FTP()
        ftp.connect(ftp_host, port)
        print("[SUCCESS] FTP server connection established")
        
        # Try multiple username formats
        login_formats = [
            (username, "Standard username"),
            (username.split('@')[0] if '@' in username else username, "Username without domain"),
            (username.split('.')[0] if '.' in username else username, "Username before first dot"),
            (f"{username}@{ftp_host}" if '@' not in username and '.' in ftp_host else username, "Username with domain"),
            (f"{ftp_host}\\{username}" if '\\' not in username else username, "Windows-style username")
        ]
        
        login_successful = False
        successful_format = None
        
        for login, description in login_formats:
            try:
                print(f"Trying login format: {login} ({description})")
                # Create a new connection for each attempt
                ftp = ftplib.FTP()
                ftp.connect(ftp_host, port)
                ftp.login(login, password)
                print(f"[SUCCESS] Login successful with format: {login}")
                login_successful = True
                successful_format = login
                break
            except Exception as e:
                print(f"[FAILED] Login failed: {str(e)}")
        
        if not login_successful:
            print("[ERROR] All login attempts failed")
            return False, "All login attempts failed"
        
        # If we got here, login was successful
        print(f"[SUCCESS] Successfully logged in with username: {successful_format}")
        
        # Get current directory
        current_dir = ftp.pwd()
        print(f"Current directory: {current_dir}")
        
        # List files in current directory
        print("Directory listing:")
        files = []
        ftp.dir(files.append)
        for file in files[:10]:
            print(f"  {file}")
        
        # Close connection
        ftp.quit()
        print("FTP connection closed successfully")
        return True, successful_format
    
    except Exception as e:
        print(f"[ERROR] FTP connection error: {str(e)}")
        return False, str(e)

def deploy_templates(templates_dir="temp_templates"):
    """Deploy templates to FTP server"""
    print("Starting template deployment...")
    
    # Initialize variables
    main_folder_counter = 1  # Default
    
    # Check if we have a saved counter value
    try:
        if os.path.exists('ftp_folder_counter.txt'):
            with open('ftp_folder_counter.txt', 'r') as f:
                content = f.read().strip()
                if content:  # Only try to convert if there's actual content
                    main_folder_counter = int(content)
        else:
            # Create the file if it doesn't exist
            with open('ftp_folder_counter.txt', 'w') as f:
                f.write('1')
                print("Created new folder counter file starting at 1")
    except Exception as e:
        print(f"Error loading folder counter: {str(e)}")
        # Always reset to 1 if there's an error
        main_folder_counter = 1
    
    # Initialize tracking object
    deployed_info = {
        'uploaded_files': 0,
        'uploaded_folders': 0,
        'websites': {},
        'errors': []
    }
    
    if not os.path.exists(templates_dir):
        error_msg = f"Templates directory '{templates_dir}' not found"
        print(f"Error: {error_msg}")
        deployed_info['errors'].append(error_msg)
        return False, error_msg
    
    # Find the actual templates directory - check if it's directly in temp_templates or in a subdirectory
    actual_templates_dir = templates_dir
    subdirs = [d for d in os.listdir(templates_dir) if os.path.isdir(os.path.join(templates_dir, d)) and d.startswith('website_templates_')]
    
    if subdirs:
        # Use the most recent website_templates directory if there are multiple
        subdirs.sort(reverse=True)  # Sort in descending order to get the most recent first
        actual_templates_dir = os.path.join(templates_dir, subdirs[0])
        print(f"Using templates from subdirectory: {actual_templates_dir}")
    
    # Test connection first
    connection_ok, login_format = test_ftp_connection()
    if not connection_ok:
        error_msg = f"FTP connection failed: {login_format}"
        deployed_info['errors'].append(error_msg)
        return False, error_msg
    
    # Fix FTP host if it includes protocol
    ftp_host = FTP_CONFIG['host']
    if ftp_host.startswith('ftp://'):
        ftp_host = ftp_host[6:]  # Remove 'ftp://' prefix
    
    # Get the base domain for URLs
    try:
        from config import DOMAIN_CONFIG
        base_domain = DOMAIN_CONFIG.get('base_domain', 'jede-website-info.de')
        access_url = DOMAIN_CONFIG.get('access_url', f"https://{base_domain}/")
    except ImportError:
        base_domain = 'jede-website-info.de'
        access_url = 'https://jede-website-info.de/'
    
    print(f"Starting deployment with main folder counter: {main_folder_counter}")
    
    try:
        print("Starting deployment...")
        
        # Connect to FTP server
        ftp = ftplib.FTP()
        ftp.connect(ftp_host, FTP_CONFIG['port'])
        ftp.login(login_format, FTP_CONFIG['password'])
        
        # Creating templates directory structure
        base_path = FTP_CONFIG['base_path'].rstrip('/')
        path_parts = base_path.lstrip('/').split('/')
        
        # Navigate to root
        try:
            ftp.cwd('/')
            print("Changed to root directory")
        except Exception as e:
            error_msg = f"Error changing to root directory: {str(e)}"
            print(error_msg)
            deployed_info['errors'].append(error_msg)
        
        # Create each part of the path
        current_path = ""
        for part in path_parts:
            if not part:  # Skip empty parts
                continue
                
            current_path += "/" + part
            try:
                ftp.cwd(current_path)
                print(f"Directory exists: {current_path}")
            except:
                try:
                    ftp.mkd(part)
                    deployed_info['uploaded_folders'] += 1
                    print(f"Created directory: {part}")
                    ftp.cwd(part)
                except Exception as e:
                    error_msg = f"Error creating/entering directory '{part}': {str(e)}"
                    print(error_msg)
                    deployed_info['errors'].append(error_msg)
                    return False, error_msg
        
        # Check for existing folders to determine the highest folder number
        try:
            folder_numbers = []
            ftp.cwd(base_path)
            folders = []
            ftp.dir(folders.append)
            
            for folder_info in folders:
                parts = folder_info.split()
                if len(parts) >= 9:  # Standard format for dir listing
                    folder_name = parts[-1]  # Last part is the name
                    if folder_name.isdigit() and len(folder_name) == 6:
                        folder_numbers.append(int(folder_name))
                    elif len(folder_name) == 6 and folder_name.startswith('0') and folder_name.replace('0', '').isdigit():
                        folder_numbers.append(int(folder_name))
            
            if folder_numbers:
                highest_folder = max(folder_numbers)
                if highest_folder >= main_folder_counter:
                    main_folder_counter = highest_folder + 1
                    print(f"Found higher folder number on server: {highest_folder}, using {main_folder_counter} for deployment")
                    # Update the local counter file
                    with open('ftp_folder_counter.txt', 'w') as f:
                        f.write(str(main_folder_counter))
        except Exception as e:
            print(f"Warning: Could not check for existing folders: {str(e)}")
            # Continue with the current counter value
        
        # Now we're in the base directory, upload each template folder
        website_folders = [d for d in os.listdir(actual_templates_dir) if os.path.isdir(os.path.join(actual_templates_dir, d))]
        
        if not website_folders:
            error_msg = "No template folders found to upload"
            deployed_info['errors'].append(error_msg)
            return False, error_msg
        
        deployed_urls = {}
        folder_mapping = {}
        
        # Create the padded main folder name
        main_folder_name = f"{main_folder_counter:06d}"
        
        def clean_domain_name(domain):
            import re
            domain = domain.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            domain = domain.split('.')[0]  # Only main part
            domain = re.sub(r'[^a-z0-9]', '', domain)  # Remove all except a-z, 0-9
            return domain
        
        # Deploy each template
        print(f"\nDeploying {len(website_folders)} templates to main folder {main_folder_name}...")
        for i, website_folder in enumerate(website_folders):
            website_path = os.path.join(actual_templates_dir, website_folder)
            if not os.path.isdir(website_path):
                continue
            
            # Extract domain from website_folder or leads.csv
            domain = website_folder.lower()
            extracted_domain = None
            matching_url = None
            
            try:
                import pandas as pd
                if os.path.exists('leads.csv'):
                    df = pd.read_csv('leads.csv')
                    # Match the website folder name with business_name in leads.csv
                    for _, row in df.iterrows():
                        # Try to match by business name first
                        business_name = str(row.get('business_name', '')).strip()
                        if business_name and (website_folder.lower().replace('_', ' ') in business_name.lower() or business_name.lower() in website_folder.lower().replace('_', ' ')):
                            url = str(row.get('url', '')).strip().lower()
                            if url:
                                matching_url = url
                                from urllib.parse import urlparse
                                url_parts = urlparse(url)
                                if url_parts.netloc:
                                    raw_domain = url_parts.netloc.lower()
                                    if raw_domain.startswith('www.'):
                                        raw_domain = raw_domain[4:]
                                    extracted_domain = raw_domain.split('.')[0]
                                    print(f"Matched {website_folder} to {business_name} with domain {extracted_domain}")
                                    break
                    
                    # If no match by business name, try direct domain matching
                    if not extracted_domain:
                        for _, row in df.iterrows():
                            url = str(row.get('url', '')).strip().lower()
                            if url:
                                from urllib.parse import urlparse
                                url_parts = urlparse(url)
                                if url_parts.netloc:
                                    raw_domain = url_parts.netloc.lower()
                                    if raw_domain.startswith('www.'):
                                        raw_domain = raw_domain[4:]
                                    domain_part = raw_domain.split('.')[0]
                                    
                                    # Check if domain part is in the website folder name
                                    if domain_part in website_folder.lower().replace('_', ''):
                                        extracted_domain = domain_part
                                        matching_url = url
                                        print(f"Matched {website_folder} to URL domain {extracted_domain}")
                                        break
            except Exception as e:
                print(f"Error extracting domain from leads.csv: {str(e)}")
                
            # If no match was found, use the website folder name
            if not extracted_domain:
                # Use the website folder name as domain
                domain = website_folder.lower()
                # Remove underscores and other special characters
                domain = clean_domain_name(domain)
                print(f"Using website folder name as domain: {domain}")
            else:
                domain = extracted_domain
                
            domain = clean_domain_name(domain)
            inner_folder_name = domain
            
            # Create main folder (00000X)
            remote_main_dir = f"{base_path}/{main_folder_name}"
            try:
                try:
                    ftp.cwd(remote_main_dir)
                except:
                    ftp.mkd(remote_main_dir)
                    ftp.cwd(remote_main_dir)
            except Exception as e:
                print(f"Error with main dir: {str(e)}"); continue
            
            # Create domain (inner) folder
            remote_inner_dir = f"{remote_main_dir}/{inner_folder_name}"
            try:
                try:
                    ftp.cwd(remote_inner_dir)
                except:
                    ftp.mkd(remote_inner_dir)
                    ftp.cwd(remote_inner_dir)
            except Exception as e:
                print(f"Error with domain dir: {str(e)}"); continue
            
            # Always create 3 style folders
            for style in ['elegant', 'minimalist', 'modern']:
                remote_style_dir = f"{remote_inner_dir}/{style}"
                try:
                    try:
                        ftp.cwd(remote_style_dir)
                    except:
                        ftp.mkd(remote_style_dir)
                        ftp.cwd(remote_style_dir)
                except Exception as e:
                    print(f"Error with style dir: {str(e)}"); continue
                
                # Upload files for this style if present
                style_path = os.path.join(os.path.join(actual_templates_dir, website_folder), style)
                if os.path.isdir(style_path):
                    upload_directory(ftp, style_path, deployed_info)
                
                # Return to main folder after uploading each style
                try:
                    ftp.cwd(remote_main_dir)
                    ftp.cwd(remote_inner_dir)
                except Exception as e:
                    print(f"Error returning to inner dir: {str(e)}")
            
            # Return to main folder after uploading all styles for this domain
            try:
                ftp.cwd(remote_main_dir)
            except Exception as e:
                print(f"Error returning to main dir: {str(e)}")
            
            # Track URLs for leads.csv
            website_urls = {
                'elegant': f"https://jede-website-info.de/{main_folder_name}/{inner_folder_name}/elegant/index.html",
                'minimalist': f"https://jede-website-info.de/{main_folder_name}/{inner_folder_name}/minimalist/index.html",
                'modern': f"https://jede-website-info.de/{main_folder_name}/{inner_folder_name}/modern/index.html",
            }
            deployed_urls[website_folder] = website_urls
            
            folder_mapping[website_folder] = {
                'main_folder': main_folder_name,
                'inner_folder': inner_folder_name,
                'domain': domain
            }
            
            # Add to domain mapping
            if domain not in folder_mapping:
                folder_mapping[domain] = {}
            
            folder_mapping[domain] = {
                'main_folder': main_folder_name,
                'inner_folder': inner_folder_name,
                'website_folder': website_folder
            }
        
        # Save folder mapping
        try:
            with open('folder_mapping.json', 'w') as f:
                import json
                json.dump(folder_mapping, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save folder mapping: {str(e)}")
        
        # Save domain to folder mapping
        try:
            with open('domain_to_ftp_mapping.json', 'w') as f:
                import json
                json.dump(folder_mapping, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save domain mapping: {str(e)}")
        
        # Save folder counters
        try:
            # Only increment main folder counter after all templates are deployed
            # We don't increment here anymore, as the counter is already updated
            # when checking for existing folders on the server
            with open('ftp_folder_counter.txt', 'w') as f:
                f.write(str(main_folder_counter))
        except Exception as e:
            print(f"Warning: Could not save folder counters: {str(e)}")
        
        # Update leads.csv with template URLs
        if deployed_urls:
            try:
                update_leads_csv_with_templates(deployed_urls)
            except Exception as e:
                print(f"Error updating leads.csv: {str(e)}")
        
        # Close the connection
        ftp.quit()
        print("FTP deployment completed successfully!")
        deployed_info['end_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
        
        return True, deployed_urls
        
    except Exception as e:
        error_msg = f"Deployment error: {str(e)}"
        print(error_msg)
        deployed_info['errors'].append(error_msg)
        return False, error_msg

def update_leads_csv_with_templates(deployed_urls):
    """Update leads.csv with template URLs after deployment"""
    import pandas as pd
    import shutil
    from datetime import datetime
    
    csv_file = "leads.csv"
    if not os.path.exists(csv_file):
        print(f"Warning: {csv_file} not found, can't update template URLs")
        return
    
    # Create a backup of the original file with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"leads_backup_{timestamp}.csv"
    shutil.copy2(csv_file, backup_file)
    print(f"Created backup of leads.csv as {backup_file}")
    
    print(f"Updating template URLs in {csv_file}")
    df = pd.read_csv(csv_file)
    
    # Load domain to FTP mapping if it exists
    domain_mapping = {}
    try:
        if os.path.exists('domain_to_ftp_mapping.json'):
            import json
            with open('domain_to_ftp_mapping.json', 'r') as f:
                domain_mapping = json.load(f)
                print(f"Loaded existing domain to FTP mapping with {len(domain_mapping)} entries")
    except Exception as e:
        print(f"Warning: Could not load domain to FTP mapping: {str(e)}")
    
    # Save folder mapping to use in other parts of the application
    try:
        # Get actual FTP folder names to ensure consistency
        with open('folder_mapping.json', 'r') as f:
            import json
            folder_mapping = json.load(f)
            
        # Create reverse mapping from original name to folder name
        reverse_mapping = {}
        for original_name, folder_info in folder_mapping.items():
            # Store the mapping in a way that allows lookup by domain
            reverse_mapping[original_name.lower()] = {
                'ftp_name': original_name,
                'main_folder': folder_info.get('main_folder', ''),
                'inner_folder': folder_info.get('inner_folder', '')
            }
            
            # Also map domain variants (with and without www)
            if 'domain' in folder_info:
                domain = folder_info['domain'].lower()
                reverse_mapping[domain] = {
                    'ftp_name': original_name,
                    'main_folder': folder_info.get('main_folder', ''),
                    'inner_folder': folder_info.get('inner_folder', '')
                }
                # Add www variant
                if not domain.startswith('www.'):
                    reverse_mapping[f"www.{domain}"] = {
                        'ftp_name': original_name,
                        'main_folder': folder_info.get('main_folder', ''),
                        'inner_folder': folder_info.get('inner_folder', '')
                    }
            
        # Save this mapping for other components to use
        with open('domain_to_ftp_mapping.json', 'w') as f:
            json.dump(reverse_mapping, f, indent=2)
            print("Saved domain to FTP folder mapping")
            
        # Update the domain_mapping with the new reverse_mapping
        domain_mapping.update(reverse_mapping)
    except Exception as e:
        print(f"Warning: Could not load folder mapping: {str(e)}")
        reverse_mapping = {}
    
    # Make sure we have all the necessary columns
    required_columns = ['template_url', 'elegant_url', 'minimalist_url', 'modern_url']
    for col in required_columns:
        if col not in df.columns:
            df[col] = ""
            
    updated = 0
    
    # For each row in the CSV, try to find matching URLs
    for idx, row in df.iterrows():
        business_name_key = None
        domain_key = None
        
        # Try business name first if available
        if pd.notna(row.get('business_name')) and row['business_name']:
            business_name_key = row['business_name']
            
        # Extract domain from URL for matching
        if pd.notna(row.get('url')) and row['url']:
            try:
                from urllib.parse import urlparse
                url = row['url'].strip()  # Clean URL
                url_parts = urlparse(url)
                if url_parts.netloc:
                    domain = url_parts.netloc.lower()
                    domain_key = domain
                    
                    # Also check domain without www
                    if domain.startswith('www.'):
                        domain_without_www = domain[4:]
                        # Check if this domain is in our mapping
                        if domain_without_www in domain_mapping:
                            domain_key = domain_without_www
                else:
                    # Try to extract domain from non-standard URL format
                    domain_parts = url.split('//')
                    if len(domain_parts) > 1:
                        domain = domain_parts[1].split('/')[0]
                        domain = domain.lower().strip()
                        domain_key = domain
            except Exception as e:
                print(f"Error parsing URL {row.get('url', '')}: {str(e)}")
                
        # Look for exact business name match
        matched_folder = None
        main_folder = None
        inner_folder = None
        
        if business_name_key:
            for folder in deployed_urls.keys():
                if folder.lower() == business_name_key.lower():
                    matched_folder = folder
                    if folder in folder_mapping:
                        folder_info = folder_mapping[folder]
                        main_folder = folder_info.get('main_folder', '')
                        inner_folder = folder_info.get('inner_folder', '')
                    break
        
        # If no match by business name, try domain
        if not matched_folder and domain_key:
            # First check if domain is in our mapping
            if domain_key in domain_mapping:
                matched_info = domain_mapping[domain_key]
                ftp_name = matched_info.get('ftp_name', '')
                if ftp_name in deployed_urls:
                    matched_folder = ftp_name
                    main_folder = matched_info.get('main_folder', '')
                    inner_folder = matched_info.get('inner_folder', '')
            
            # If still no match, try partial matching
            if not matched_folder:
                for folder in deployed_urls.keys():
                    if domain_key.lower() in folder.lower() or folder.lower() in domain_key.lower():
                        matched_folder = folder
                        if folder in folder_mapping:
                            folder_info = folder_mapping[folder]
                            main_folder = folder_info.get('main_folder', '')
                            inner_folder = folder_info.get('inner_folder', '')
                        break
                    
        # If we found a match, update template URLs
        if matched_folder and matched_folder in deployed_urls and main_folder and inner_folder:
            styles = deployed_urls[matched_folder]
            
            # Check if any URLs have changed before updating
            urls_changed = False
            
            # Update main template URL (prefer elegant)
            if 'elegant' in styles:
                # Use the new format: 000005/1/elegant/index.html
                url = f"https://jede-website-info.de/{main_folder}/{inner_folder}/elegant/index.html"
                
                # Only update if empty or different to avoid unnecessary changes
                if not pd.notna(row.get('template_url')) or not row['template_url'] or row['template_url'] != url:
                    df.at[idx, 'template_url'] = url
                    urls_changed = True
                if not pd.notna(row.get('elegant_url')) or not row['elegant_url'] or row['elegant_url'] != url:
                    df.at[idx, 'elegant_url'] = url
                    urls_changed = True
            
            # Update style-specific URLs 
            if 'minimalist' in styles:
                url = f"https://jede-website-info.de/{main_folder}/{inner_folder}/minimalist/index.html"
                
                if not pd.notna(row.get('minimalist_url')) or not row['minimalist_url'] or row['minimalist_url'] != url:
                    df.at[idx, 'minimalist_url'] = url
                    urls_changed = True
                
            if 'modern' in styles:
                url = f"https://jede-website-info.de/{main_folder}/{inner_folder}/modern/index.html"
                
                if not pd.notna(row.get('modern_url')) or not row['modern_url'] or row['modern_url'] != url:
                    df.at[idx, 'modern_url'] = url
                    urls_changed = True
                
            if urls_changed:
                updated += 1
    
    # Only save if we actually made changes
    if updated > 0:
        df.to_csv(csv_file, index=False)
        print(f"Updated template URLs for {updated} leads in {csv_file}")
    else:
        print(f"No updates needed for leads.csv")

def upload_directory(ftp, local_path, deployed_info=None):
    """Upload all files in a directory recursively"""
    files_count = 0
    
    for item in os.listdir(local_path):
        local_item_path = os.path.join(local_path, item)
        
        # Handle directories
        if os.path.isdir(local_item_path):
            try:
                ftp.mkd(item)
                if deployed_info:
                    deployed_info['uploaded_folders'] += 1
                print(f"Created directory: {item}")
            except:
                print(f"Directory already exists: {item}")
            
            # Navigate into the directory
            ftp.cwd(item)
            
            # Recursively upload contents
            files_count += upload_directory(ftp, local_item_path, deployed_info)
            
            # Navigate back up
            ftp.cwd('..')
            
        # Handle files
        elif os.path.isfile(local_item_path):
            try:
                # Upload with original filename to preserve HTML references
                with open(local_item_path, 'rb') as file:
                    ftp.storbinary(f'STOR {item}', file)
                
                print(f"Uploaded: {item}")
                files_count += 1
                
                if deployed_info:
                    deployed_info['uploaded_files'] += 1
            except Exception as e:
                error_msg = f"Error uploading {item}: {str(e)}"
                print(error_msg)
                if deployed_info and 'errors' in deployed_info:
                    deployed_info['errors'].append(error_msg)
    
    return files_count

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Run the deployment
    print("Starting manual deployment...")
    success, result = deploy_templates()
    
    if success:
        print("\n--- DEPLOYMENT SUCCESSFUL ---")
        print("Deployed URLs:")
        for website, styles in result.items():
            for style, url in styles.items():
                print(f"  {website}: {style} → {url}")
    else:
        print("\n!!! DEPLOYMENT FAILED !!!")
        print(f"Error: {result}")
        
    print("\nDeployment script completed.") 