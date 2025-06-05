from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
import pandas as pd
import logging
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import ssl
import time
import traceback

email_sender_bp = Blueprint('email_sender', __name__, template_folder='templates')

# Logging setup (optional, if not already configured)
logging.basicConfig(
    filename='email_logs.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def load_leads():
    try:
        df = pd.read_csv('leads.csv')
        return df.to_dict('records')
    except Exception as e:
        logging.error(f"Error loading leads: {str(e)}")
        return []

@email_sender_bp.route('/email-sender', methods=['GET', 'POST'])
def email_sender_page():
    if request.method == 'POST':
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
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ text-align: center; margin-bottom: 20px; }}
                    .content {{ margin-bottom: 30px; }}
                    .template-section {{ margin-bottom: 25px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                    .template-title {{ font-weight: bold; margin-bottom: 10px; }}
                    .footer {{ text-align: center; font-size: 12px; color: #777; }}
                    .logo {{ max-width: 200px; max-height: 80px; margin-bottom: 15px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>Hello {lead['business_name']}</h2>
                        {f'<img src="{lead["logo"]}" alt="{lead["business_name"]} Logo" class="logo">' if lead.get('logo') else ''}
                    </div>
                    <div class="content">
                        <p>We've created beautiful website templates for your business.</p>
                        <p>Please find below three different design options for your consideration:</p>
                        
                        <div class="template-section">
                            <div class="template-title">Elegant Design</div>
                            <p>A sophisticated and professional design with elegant typography and layout.</p>
                            <p>View it here: <a href="{lead['elegant_url']}">{lead['elegant_url']}</a></p>
                        </div>
                        
                        <div class="template-section">
                            <div class="template-title">Minimalist Design</div>
                            <p>A clean, simple design focusing on content with minimal distractions.</p>
                            <p>View it here: <a href="{lead['minimalist_url']}">{lead['minimalist_url']}</a></p>
                        </div>
                        
                        <div class="template-section">
                            <div class="template-title">Modern Design</div>
                            <p>A contemporary design with modern elements and visual appeal.</p>
                            <p>View it here: <a href="{lead['modern_url']}">{lead['modern_url']}</a></p>
                        </div>
                        
                        <p>Please let us know which design you prefer or if you'd like any customizations.</p>
                    </div>
                    <div class="footer">
                        <p>This email was sent to {lead['email']} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p>From: {sender_email}</p>
                    </div>
                </div>
            </body>
            </html>
            """
            # SMTP logic (Strato/Hostinger)
            if any(domain in sender_email for domain in [
                'mail-jede-website.de', 'jede-website-mail.de', 'jede-website-email.de', 'email-jede-website.de'
            ]):
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

@email_sender_bp.route('/email-sender/preview', methods=['POST'])
def email_sender_preview():
    try:
        # Log all request data for debugging
        logging.info(f"Preview request received with data: {request.form}")
        logging.info(f"Request JSON: {request.get_json(silent=True)}")
        logging.info(f"Request data: {request.data}")
        
        # Try to get lead_index from various sources
        lead_index = None
        if request.form and 'lead_index' in request.form:
            lead_index = request.form.get('lead_index')
        elif request.get_json(silent=True) and 'lead_index' in request.get_json(silent=True):
            lead_index = request.get_json(silent=True).get('lead_index')
        else:
            # Try to parse the request body as raw data
            try:
                data_dict = {}
                for item in request.data.decode('utf-8').split('&'):
                    if '=' in item:
                        key, value = item.split('=')
                        data_dict[key] = value
                if 'lead_index' in data_dict:
                    lead_index = data_dict['lead_index']
            except:
                pass
        
        if lead_index is None:
            return jsonify({'error': 'No lead index provided'})
            
        # Convert to integer
        try:
            lead_index = int(lead_index)
        except ValueError:
            return jsonify({'error': f'Invalid lead index format: {lead_index}'})
        
        # Load leads and check index bounds
        leads = load_leads()
        if lead_index >= len(leads):
            return jsonify({'error': f'Invalid lead index: {lead_index}. Max index is {len(leads)-1}'})
            
        lead = leads[lead_index]
        logging.info(f"Preview request for lead: {lead}")
        
        # Check if the required fields exist in the lead data
        required_fields = ['email', 'business_name']
        for field in required_fields:
            if field not in lead or not lead[field]:
                lead[field] = f'Missing {field}'
                
        # Handle URL fields that might be missing
        for url_field in ['elegant_url', 'minimalist_url', 'modern_url']:
            if url_field not in lead or not lead[url_field]:
                lead[url_field] = '#'
        
        # Get form values from various sources
        sender_email = None
        subject = None
        
        if request.form:
            sender_email = request.form.get('sender_email')
            subject = request.form.get('subject')
        elif request.get_json(silent=True):
            sender_email = request.get_json(silent=True).get('sender_email')
            subject = request.get_json(silent=True).get('subject')
        
        # Default values if not found
        if not sender_email:
            sender_email = 'example@email.com'
        if not subject:
            subject = 'Your Custom Website Template'
        
        preview_data = {
            'recipient': lead['email'],
            'business_name': lead['business_name'],
            'elegant_url': lead.get('elegant_url', '#'),
            'minimalist_url': lead.get('minimalist_url', '#'),
            'modern_url': lead.get('modern_url', '#'),
            'logo': lead.get('logo', ''),
            'sender_email': sender_email,
            'subject': subject
        }
        
        # Log the preview data being sent back
        logging.info(f"Sending preview data: {preview_data}")
        
        return jsonify(preview_data)
    except Exception as e:
        error_message = str(e)
        logging.error(f"Error in email preview: {error_message}")
        logging.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': f'Error generating preview: {error_message}'})

@email_sender_bp.route('/email-sender/logs')
def view_logs():
    try:
        with open('email_logs.log', 'r') as f:
            logs = f.readlines()
        return render_template('logs.html', logs=logs)
    except Exception as e:
        flash(f"Error reading logs: {str(e)}", 'error')
        return redirect(url_for('email_sender.email_sender_page'))

@email_sender_bp.route('/email-sender/send', methods=['POST'])
def send_emails():
    try:
        # Get form data
        use_rotation = request.form.get('use_rotation') == 'on'
        sender_email = request.form.get('sender_email')
        sender_password = request.form.get('sender_password')
        subject = request.form.get('subject')
        selected_leads = request.form.getlist('selected_leads')
        template_type = request.form.get('template_type', 'elegant')
        
        # Validate required fields
        if not sender_password or not subject or not selected_leads:
            flash('Missing required fields. Please fill out all required fields.', 'error')
            return redirect(url_for('email_sender.email_sender_page'))
            
        # Define Hostinger email accounts for rotation (only Hostinger emails)
        hostinger_emails = [
            'info@jede-website-info.de',
            'kontakt@info-jede-website.de',
            'info@kontakt-jede-website.de',
            'info@jede-website-kontakt.de',
            'kontakt@info-website-jede.de',
            'info@kontakt-website-jede.de',
            'info@email-website-jede.de',
            'info@jede-webseite.de',
            'kontakt@info-jede-webseite.de',
            'info@email-jede-webseite.de',
            'kontakt@jede-webseite-info.de',
            'info@jede-webseite-kontakt.de',
            'info@jede-webseite-mail.de',
            'info@jede-webseite-email.de'
        ]
        
        # Force Hostinger email usage when rotation is enabled
        if use_rotation:
            logging.info("Email rotation enabled - using only Hostinger email accounts")
        
        # If rotation is enabled, ignore sender_email from form
        if not use_rotation and not sender_email:
            flash('Please select a sender email or enable email rotation.', 'error')
            return redirect(url_for('email_sender.email_sender_page'))
        
        leads = load_leads()
        results = []
        rotation_index = 0
        
        for lead_index in selected_leads:
            lead_index = int(lead_index)
            if lead_index >= len(leads):
                continue
                
            lead = leads[lead_index]
            
            # If rotation is enabled, use the next email in the rotation
            if use_rotation:
                sender_email = hostinger_emails[rotation_index % len(hostinger_emails)]
                rotation_index += 1
                logging.info(f"Using rotated email account: {sender_email}")
            
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ text-align: center; margin-bottom: 20px; }}
                    .content {{ margin-bottom: 30px; }}
                    .template-section {{ margin-bottom: 25px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                    .template-title {{ font-weight: bold; margin-bottom: 10px; }}
                    .footer {{ text-align: center; font-size: 12px; color: #777; }}
                    .logo {{ max-width: 200px; max-height: 80px; margin-bottom: 15px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>Hello {lead['business_name']}</h2>
                        {f'<img src="{lead["logo"]}" alt="{lead["business_name"]} Logo" class="logo">' if lead.get('logo') else ''}
                    </div>
                    <div class="content">
                        <p>We've created beautiful website templates for your business.</p>
                        <p>Please find below three different design options for your consideration:</p>
                        
                        <div class="template-section">
                            <div class="template-title">Elegant Design</div>
                            <p>A sophisticated and professional design with elegant typography and layout.</p>
                            <p>View it here: <a href="{lead.get('elegant_url', '#')}">Elegant Design</a></p>
                        </div>
                        
                        <div class="template-section">
                            <div class="template-title">Minimalist Design</div>
                            <p>A clean, simple design focusing on content with minimal distractions.</p>
                            <p>View it here: <a href="{lead.get('minimalist_url', '#')}">Minimalist Design</a></p>
                        </div>
                        
                        <div class="template-section">
                            <div class="template-title">Modern Design</div>
                            <p>A contemporary design with modern elements and visual appeal.</p>
                            <p>View it here: <a href="{lead.get('modern_url', '#')}">Modern Design</a></p>
                        </div>
                        
                        <p>Please let us know which design you prefer or if you'd like any customizations.</p>
                    </div>
                    <div class="footer">
                        <p>This email was sent to {lead['email']} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p>From: {sender_email}</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Determine SMTP server based on sender email
            if any(domain in sender_email for domain in [
                'mail-jede-website.de', 'jede-website-mail.de', 'jede-website-email.de', 'email-jede-website.de'
            ]):
                smtp_server = 'smtp.strato.de'
            else:
                smtp_server = 'smtp.hostinger.com'
            port = 465
            
            try:
                # Set up the SMTP server
                logging.info(f"Attempting to send email to {lead['email']} from {sender_email} using {smtp_server}")
                server = smtplib.SMTP_SSL(smtp_server, port, context=ssl.create_default_context())
                server.login(sender_email, sender_password)
                
                # Create the email
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = sender_email
                msg['To'] = lead['email']
                msg.attach(MIMEText(html_content, 'html'))
                
                # Send the email
                server.sendmail(sender_email, lead['email'], msg.as_string())
                server.quit()
                
                # Add a 1-second delay between emails when using rotation
                if use_rotation and lead_index != selected_leads[-1]:  # Don't delay after the last email
                    time.sleep(1)
                
                results.append({
                    'email': lead['email'],
                    'business_name': lead['business_name'],
                    'success': True,
                    'message': 'Email sent successfully',
                    'sender_email': sender_email
                })
                logging.info(f"Email sent successfully to {lead['email']}")
                
            except Exception as e:
                error_message = str(e)
                results.append({
                    'email': lead['email'],
                    'business_name': lead['business_name'],
                    'success': False,
                    'message': error_message,
                    'sender_email': sender_email
                })
                logging.error(f"Failed to send email to {lead['email']}: {error_message}")
        
        return render_template('results.html', results=results)
        
    except Exception as e:
        error_message = str(e)
        logging.error(f"Error in send_emails: {error_message}")
        flash(f"An error occurred: {error_message}", 'error')
        return redirect(url_for('email_sender.email_sender_page'))
