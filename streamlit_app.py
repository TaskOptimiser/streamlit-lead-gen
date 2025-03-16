import streamlit as st
import requests
import json
import uuid
import time
import smtplib
import email.utils
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
from datetime import datetime
import base64
import hashlib
import hmac
import os
from cryptography.fernet import Fernet
import threading
from collections import deque

# Page config
st.set_page_config(
    page_title="LinkedIn Lead Generator",
    page_icon="📊",
    layout="wide"
)

# Initialize session state variables if they don't exist
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'users' not in st.session_state:
    # For demo purposes - in production use a database
    # Format: {username: {password_hash: hash, key: encryption_key}}
    st.session_state.users = {
        "admin": {
            "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
            "key": Fernet.generate_key().decode()
        }
    }
if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if 'scraper_logs' not in st.session_state:
    st.session_state.scraper_logs = deque(maxlen=100)
if 'scraped_leads' not in st.session_state:
    st.session_state.scraped_leads = []
if 'email_sent_today' not in st.session_state:
    st.session_state.email_sent_today = 0
if 'last_email_date' not in st.session_state:
    st.session_state.last_email_date = datetime.now().date()


# ----- UTILITY FUNCTIONS -----

def encrypt_data(data, key):
    """Encrypt sensitive data"""
    f = Fernet(key.encode())
    return f.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data, key):
    """Decrypt sensitive data"""
    f = Fernet(key.encode())
    return f.decrypt(encrypted_data.encode()).decode()

def validate_password(username, password):
    """Validate user credentials"""
    if username in st.session_state.users:
        stored_hash = st.session_state.users[username]["password_hash"]
        if hashlib.sha256(password.encode()).hexdigest() == stored_hash:
            return True
    return False

def send_to_webhook(payload):
    """Send data to n8n webhook"""
    webhook_url = st.session_state.get('webhook_url', 'https://n8n.yourdomain.com/webhook/linkedin-scraper')
    try:
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error connecting to webhook: {str(e)}")
        return None

def format_log_entry(log):
    """Format log entry for display"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    return f"[{timestamp}] {log}"

def add_log(message):
    """Add log to session state and display"""
    st.session_state.scraper_logs.append(format_log_entry(message))
    
def send_email(recipient, subject, body, smtp_config):
    """Send an email using the configured SMTP settings"""
    # Check if we've hit the daily limit
    current_date = datetime.now().date()
    if current_date > st.session_state.last_email_date:
        st.session_state.email_sent_today = 0
        st.session_state.last_email_date = current_date
        
    if st.session_state.email_sent_today >= st.session_state.email_limit:
        return False, "Daily email limit reached"
    
    try:
        msg = MIMEMultipart()
        msg['To'] = recipient
        msg['From'] = smtp_config['email']
        msg['Subject'] = subject
        msg['Date'] = email.utils.formatdate(localtime=True)
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(smtp_config['server'], int(smtp_config['port']))
        server.starttls()
        server.login(smtp_config['username'], smtp_config['password'])
        server.send_message(msg)
        server.quit()
        
        st.session_state.email_sent_today += 1
        return True, f"Email sent to {recipient}. ({st.session_state.email_sent_today}/{st.session_state.email_limit} sent today)"
    
    except Exception as e:
        return False, f"Failed to send email: {str(e)}"

def personalize_template(template, lead_data):
    """Replace placeholders in email template with lead data"""
    personalized = template
    for key, value in lead_data.items():
        placeholder = f"{{{{{key}}}}}"
        personalized = personalized.replace(placeholder, str(value))
    return personalized


# ----- UI COMPONENTS -----

def show_login():
    """Display login form"""
    st.markdown("## LinkedIn Lead Generator - Login")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        
        if st.button("Logout", key="logout_button"):
            if validate_password(username, password):
                st.session_state.authenticated = True
                st.session_state.current_user = username
                st.session_state.encryption_key = st.session_state.users[username]["key"]
                st.rerun()
            else:
                st.error("Invalid username or password")
    
    with col2:
        st.markdown("""
        ### Demo Credentials
        - Username: admin
        - Password: admin123
        
        *Note: In production, implement proper user registration and database storage*
        """)

def show_app():
    """Display main application after login"""
    st.markdown("# LinkedIn Lead Generator")
    
    tab1, tab2, tab3, tab4 = st.tabs(["Configuration", "Scraper Status", "Leads & Emails", "Settings"])
    
    with tab1:
        show_configuration_tab()
    
    with tab2:
        show_scraper_status_tab()
    
    with tab3:
        show_leads_email_tab()
    
    with tab4:
        show_settings_tab()

def show_configuration_tab():
    """Display configuration inputs"""
    st.markdown("## Configuration")
    
    with st.expander("LinkedIn Sales Navigator Configuration", expanded=True):
        linkedin_cookie = st.text_area(
            "LinkedIn Sales Navigator Cookie JSON",
            help="Paste your LinkedIn Sales Navigator cookie JSON here. This is used for authentication."
        )
        
        linkedin_search_url = st.text_input(
            "LinkedIn Sales Navigator Search URL",
            help="Enter a LinkedIn Sales Navigator search URL that defines your target audience."
        )
        
        leads_count = st.number_input(
            "Number of Leads to Generate",
            min_value=1,
            max_value=1000,
            value=50,
            help="Specify how many leads to generate from the search results."
        )
    
    with st.expander("Email Configuration", expanded=True):
        email_address = st.text_input(
            "Email Address",
            help="Your email address that will be used as the sender."
        )
        
        smtp_server = st.text_input(
            "SMTP Server",
            value="smtp.gmail.com",
            help="SMTP server address (e.g., smtp.gmail.com for Gmail)."
        )
        
        smtp_port = st.number_input(
            "SMTP Port",
            min_value=1,
            max_value=65535,
            value=587,
            help="SMTP server port (typically 587 for TLS or 465 for SSL)."
        )
        
        smtp_username = st.text_input(
            "SMTP Username",
            help="Your SMTP username (often the same as your email address)."
        )
        
        smtp_password = st.text_input(
            "SMTP Password",
            type="password",
            help="Your SMTP password or app password (for Gmail, you'll need to create an app password)."
        )
        
        email_mode = st.selectbox(
            "Email Sending Mode",
            options=["Immediate Send", "Schedule Send"],
            help="Choose how you want emails to be sent."
        )
        
        email_limit = st.number_input(
            "Daily Email Limit",
            min_value=1,
            max_value=2000,
            value=50,
            help="Set a limit for the number of emails sent per day to avoid spam detection."
        )
        st.session_state.email_limit = email_limit
    
    with st.expander("n8n Webhook Configuration", expanded=True):
        webhook_url = st.text_input(
            "n8n Webhook URL",
            value="https://n8n.yourdomain.com/webhook/linkedin-scraper",
            help="URL of your n8n webhook that will process the scraping and email tasks."
        )
        st.session_state.webhook_url = webhook_url
    
    if st.button("Start Lead Generation", type="primary"):
        if not linkedin_cookie or not linkedin_search_url:
            st.error("LinkedIn cookie and search URL are required.")
            return
        
        if not email_address or not smtp_server or not smtp_username or not smtp_password:
            st.error("Email configuration is incomplete.")
            return
        
        # Store SMTP config securely
        st.session_state.smtp_config = {
            "email": email_address,
            "server": smtp_server,
            "port": smtp_port,
            "username": smtp_username,
            "password": smtp_password,  # In production, encrypt this
            "mode": email_mode
        }
        
        # Create payload for webhook
        payload = {
            "sessionId": st.session_state.session_id,
            "linkedinCookie": json.loads(linkedin_cookie) if linkedin_cookie.strip() else {},
            "searchUrl": linkedin_search_url,
            "leadsCount": int(leads_count),
            "emailConfig": {
                "email": email_address,
                "server": smtp_server,
                "port": int(smtp_port),
                "username": smtp_username,
                # In production, use a more secure way to transmit passwords
                "password": encrypt_data(smtp_password, st.session_state.encryption_key),
                "mode": email_mode,
                "dailyLimit": int(email_limit)
            }
        }
        
        # Send to webhook
        add_log("Sending request to n8n webhook...")
        
        # For demonstration, simulate webhook response
        # In production, use the actual webhook response
        st.session_state.is_scraping = True
        
        # Start a background thread to simulate scraping updates
        threading.Thread(target=simulate_scraping, args=(leads_count,)).start()
        
        st.success("Lead generation started! Check the Scraper Status tab for progress.")
        
        # In production, actually send to webhook:
        # response = send_to_webhook(payload)
        # if response and response.get("success"):
        #     st.success("Lead generation started! Check the Scraper Status tab for progress.")
        # else:
        #     st.error("Failed to start lead generation. Please check your configuration.")

def simulate_scraping(lead_count):
    """Simulate scraper activity for demonstration purposes"""
    total_leads = lead_count
    scraped = 0
    
    add_log("Initializing LinkedIn Sales Navigator scraper...")
    time.sleep(2)
    
    add_log("Authenticating with LinkedIn...")
    time.sleep(3)
    
    add_log("Starting search query...")
    time.sleep(2)
    
    # Generate sample leads while "scraping"
    sample_companies = ["Acme Inc", "TechGiant", "Digital Solutions", "InnovateCorp", 
                       "Global Systems", "NextGen Tech", "Future Dynamics", "Elite Enterprises"]
    sample_positions = ["CEO", "CTO", "Marketing Director", "Sales Manager", 
                       "VP of Operations", "Product Manager", "Director of Engineering", "CFO"]
    sample_locations = ["New York", "San Francisco", "London", "Berlin", 
                       "Singapore", "Sydney", "Toronto", "Paris"]
    
    leads = []
    
    while scraped < total_leads:
        batch_size = min(5, total_leads - scraped)
        scraped += batch_size
        
        # Create sample leads
        for i in range(batch_size):
            import random
            first_name = random.choice(["John", "Jane", "Michael", "Sarah", "David", "Emma", "Robert", "Lisa"])
            last_name = random.choice(["Smith", "Johnson", "Brown", "Taylor", "Miller", "Davis", "Wilson", "Moore"])
            company = random.choice(sample_companies)
            position = random.choice(sample_positions)
            location = random.choice(sample_locations)
            profile_url = f"https://www.linkedin.com/in/{first_name.lower()}-{last_name.lower()}-{random.randint(10000, 99999)}"
            
            lead = {
                "firstName": first_name,
                "lastName": last_name,
                "fullName": f"{first_name} {last_name}",
                "position": position,
                "company": company,
                "location": location,
                "profileUrl": profile_url,
                "email": f"{first_name.lower()}.{last_name.lower()}@{company.lower().replace(' ', '')}.com"
            }
            leads.append(lead)
        
        add_log(f"Scraped {scraped}/{total_leads} leads...")
        time.sleep(random.uniform(1.5, 4.0))
    
    add_log(f"Lead generation complete! {total_leads} leads found.")
    st.session_state.scraped_leads = leads
    st.session_state.is_scraping = False

def show_scraper_status_tab():
    """Display scraper status and logs"""
    st.markdown("## Scraper Status")
    
    status_col, progress_col = st.columns([3, 1])
    
    with status_col:
        if st.session_state.get('is_scraping', False):
            st.info("⏳ Scraping in progress...")
        elif len(st.session_state.scraped_leads) > 0:
            st.success(f"✅ Scraping complete! {len(st.session_state.scraped_leads)} leads found.")
        else:
            st.info("Waiting to start scraping. Configure and start from the Configuration tab.")
    
    with progress_col:
        if st.session_state.get('is_scraping', False):
            st.markdown(f"Session ID: `{st.session_state.session_id[:8]}...`")
    
    # Display logs
    st.markdown("### Activity Logs")
    log_container = st.container()
    
    with log_container:
        log_text = "\n".join(st.session_state.scraper_logs)
        st.code(log_text, language="text")
    
    if st.button("Clear Logs"):
        st.session_state.scraper_logs = deque(maxlen=100)
        st.rerun()

def show_leads_email_tab():
    """Display scraped leads and email functionality"""
    st.markdown("## Leads & Email Management")
    
    if not st.session_state.scraped_leads:
        st.info("No leads found yet. Start scraping from the Configuration tab.")
        return
    
    # Display leads table
    leads_df = pd.DataFrame(st.session_state.scraped_leads)
    
    st.markdown(f"### Found {len(leads_df)} Leads")
    
    # Add selection column
    leads_df['Select'] = False
    
    # Display editable dataframe
    edited_df = st.data_editor(
        leads_df,
        column_config={
            "Select": st.column_config.CheckboxColumn(
                "Select",
                help="Select leads to send emails to",
                default=False,
            ),
            "profileUrl": st.column_config.LinkColumn("LinkedIn Profile")
        },
        disabled=["firstName", "lastName", "fullName", "position", "company", "location", "profileUrl", "email"],
        hide_index=True,
    )
    
    # Email template section
    st.markdown("### Email Template")
    
    default_template = """
    <p>Hello {{firstName}},</p>
    
    <p>I noticed your profile as {{position}} at {{company}} and I'm impressed with your background.</p>
    
    <p>I'd love to connect with you to discuss how our services might help {{company}} with [Your Value Proposition].</p>
    
    <p>Would you be available for a quick 15-minute call this week?</p>
    
    <p>Best regards,<br>
    [Your Name]<br>
    [Your Company]<br>
    [Your Contact Info]</p>
    """
    
    email_template = st.text_area(
        "Email Template (HTML supported)",
        value=default_template,
        height=300,
        help="Use {{placeholders}} for personalization. Available placeholders: {{firstName}}, {{lastName}}, {{fullName}}, {{position}}, {{company}}, {{location}}"
    )
    
    email_subject = st.text_input(
        "Email Subject",
        value="Connecting with {{company}}",
        help="Subject line for your emails. Placeholders can be used here too."
    )
    
    # Email preview
    if st.session_state.scraped_leads:
        with st.expander("Preview Personalized Email", expanded=False):
            preview_lead = st.session_state.scraped_leads[0]
            st.markdown("### Email Preview")
            st.markdown(f"**To:** {preview_lead['email']}")
            st.markdown(f"**Subject:** {personalize_template(email_subject, preview_lead)}")
            st.markdown(f"**Body:**")
            st.markdown(personalize_template(email_template, preview_lead), unsafe_allow_html=True)
    
    # Email sending section
    selected_leads = edited_df[edited_df['Select'] == True]
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown(f"### Email Sending ({len(selected_leads)} leads selected)")
        send_mode = st.radio(
            "Sending Mode",
            ["Send Now", "Test Mode (send to yourself)"],
            index=1,
            help="Test Mode will send all emails to your own address for testing."
        )
    
    with col2:
        st.markdown("### Daily Email Limits")
        st.progress(min(1.0, st.session_state.email_sent_today / st.session_state.email_limit))
        st.markdown(f"**{st.session_state.email_sent_today}/{st.session_state.email_limit}** emails sent today")
        
        if st.session_state.email_sent_today >= st.session_state.email_limit:
            st.warning("Daily email limit reached. No more emails can be sent today.")
    
    # Send email button
    if st.button("Send Emails to Selected Leads", disabled=len(selected_leads) == 0):
        if not hasattr(st.session_state, 'smtp_config'):
            st.error("Email configuration not found. Please set up your email settings in the Configuration tab.")
            return
        
        smtp_config = st.session_state.smtp_config
        
        # Create progress bar
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Send emails
        success_count = 0
        failure_count = 0
        
        for i, (_, lead) in enumerate(selected_leads.iterrows()):
            progress = (i + 1) / len(selected_leads)
            progress_bar.progress(progress)
            
            try:
                # Personalize email content
                personalized_subject = personalize_template(email_subject, lead)
                personalized_body = personalize_template(email_template, lead)
                
                # Determine recipient
                if send_mode == "Test Mode (send to yourself)":
                    recipient = smtp_config['email']
                    personalized_subject = f"[TEST] {personalized_subject} (to: {lead['email']})"
                else:
                    recipient = lead['email']
                
                status_text.info(f"Sending email to {recipient}...")
                
                # Send email
                success, message = send_email(
                    recipient=recipient,
                    subject=personalized_subject,
                    body=personalized_body,
                    smtp_config=smtp_config
                )
                
                if success:
                    success_count += 1
                    add_log(f"Email sent successfully to {recipient}")
                else:
                    failure_count += 1
                    add_log(f"Failed to send email to {recipient}: {message}")
                
                status_text.info(message)
                
                # Add delay between emails to avoid triggering spam filters
                if i < len(selected_leads) - 1:
                    time.sleep(1)
            
            except Exception as e:
                failure_count += 1
                add_log(f"Error sending email: {str(e)}")
                status_text.error(f"Error: {str(e)}")
                time.sleep(1)
        
        # Final status
        if success_count > 0 and failure_count == 0:
            st.success(f"✅ Successfully sent {success_count} emails!")
        elif success_count > 0 and failure_count > 0:
            st.warning(f"⚠️ Sent {success_count} emails with {failure_count} failures.")
        else:
            st.error(f"❌ Failed to send any emails. Check the logs for details.")

def show_settings_tab():
    """Display application settings"""
    st.markdown("## Settings")
    
    with st.expander("Application Settings", expanded=True):
        # Reset session
        if st.button("Reset Session"):
            for key in list(st.session_state.keys()):
                if key not in ['authenticated', 'users', 'current_user', 'encryption_key']:
                    del st.session_state[key]
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.scraper_logs = deque(maxlen=100)
            st.session_state.scraped_leads = []
            st.session_state.email_sent_today = 0
            st.session_state.last_email_date = datetime.now().date()
            st.rerun()
        
        # Logout button
        if st.button("Logout", key="logout_button"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    
    with st.expander("About", expanded=True):
        st.markdown("""
        ### LinkedIn Lead Generator
        
        This application helps you:
        
        1. Scrape leads from LinkedIn Sales Navigator based on your search criteria
        2. Manage and filter your leads
        3. Send personalized emails to your prospects
        
        **Note:** This application is for demonstration purposes. In a production environment:
        - Implement proper user authentication and data storage
        - Ensure secure handling of credentials
        - Comply with LinkedIn's terms of service and email regulations
        """)


# ----- MAIN APPLICATION -----

def main():
    """Main application logic"""
    # Display header
    st.sidebar.image("https://via.placeholder.com/150x50.png?text=Lead+Gen", width=200)
    st.sidebar.markdown("---")
    
    # Application flow based on authentication state
    if st.session_state.authenticated:
        # Show user info and logout option in sidebar
        st.sidebar.markdown(f"**Logged in as:** {st.session_state.current_user}")
        if st.sidebar.button("Logout"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        
        # Show main application
        show_app()
    else:
        # Show login screen
        show_login()
    
    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown("© 2025 LinkedIn Lead Generator")


if __name__ == "__main__":
    main()