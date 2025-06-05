"""
Configuration settings for the application
"""

# FTP Configuration for deployment
FTP_CONFIG = {
    'host': 'jede-website-info.de',  # FTP hostname
    'username': 'u580039661',  # FTP username
    'password': 'Website1234!?',  # FTP password
    'base_path': '/domains/jede-website-info.de/public_html',  # Base path on the server
    'use_sftp': False,  # Use SFTP instead of FTP
    'port': 21  # Default FTP port
}

# Main domain for subdomains and access
DOMAIN_CONFIG = {
    'base_domain': 'jede-website.de',  # Main domain for creating subdomains
    'access_url': 'https://www.jede-website.de/templates/'  # Base URL for accessing templates
}

# URL Configuration for deployed templates
DEPLOYED_URL_BASE = 'https://jede-website-info.de/'

# Starting ID for template URLs
STARTING_SITE_ID = 1111110 