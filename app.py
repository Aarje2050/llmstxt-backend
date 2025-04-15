from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from scraper.crawler import crawl_website
from scraper.generator import generate_llms_txt, generate_md_files, remove_md_extensions
import os
import json
import traceback
import re
import bcrypt
import jwt
import datetime
import secrets
from pymongo import MongoClient
from bson.objectid import ObjectId
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

app = Flask(__name__)
CORS(app, 
     resources={r"/api/*": {"origins": ["https://llmstxt-nextjs.vercel.app"]}},
     supports_credentials=True)  # Important for sending cookies cross-origin

# MongoDB connection
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
client = MongoClient(MONGODB_URI)
db = client.llms_txt_generator

# JWT Secret
JWT_SECRET = os.environ.get("JWT_SECRET", "your_production_secret_key")



# Function to send OTP email
def send_otp_email(to_email, otp, name):
    try:
        # Get email settings from environment variables
        email_host = os.environ.get('EMAIL_HOST', 'smtp-relay.brevo.com')
        email_port = int(os.environ.get('EMAIL_PORT', 587))
        email_secure = os.environ.get('EMAIL_SECURE', 'false').lower() == 'true'
        email_user = os.environ.get('EMAIL_USER')
        email_password = os.environ.get('EMAIL_PASSWORD')
        email_from = os.environ.get('EMAIL_FROM', '"LLM TXT GENERATOR" <noreply@immortalseo.com>')
        
        # Create message
        message = MIMEMultipart('alternative')
        message['Subject'] = 'Your Verification Code for LLMs.txt Generator'
        message['From'] = email_from
        message['To'] = to_email
        
        # Create HTML content
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>Verify your email address</h2>
            <p>Hello {name},</p>
            <p>Thank you for registering with LLMs.txt Generator. Please use the verification code below to complete your registration:</p>
            <div style="background-color: #f4f4f4; padding: 15px; text-align: center; font-size: 24px; letter-spacing: 5px; margin: 20px 0;">
                <strong>{otp}</strong>
            </div>
            <p>This code will expire in 15 minutes.</p>
            <p>If you didn't request this verification, you can safely ignore this email.</p>
            <p>Best regards,<br>The LLMs.txt Generator Team</p>
        </div>
        """
        
        # Attach HTML content
        message.attach(MIMEText(html, 'html'))
        
        # Connect to SMTP server
        server = smtplib.SMTP(email_host, email_port)
        if email_secure:
            server.starttls()
        
        # Login and send
        if email_user and email_password:
            server.login(email_user, email_password)
        
        server.sendmail(email_from, to_email, message.as_string())
        server.quit()
        
        print(f"OTP email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"Failed to send OTP email: {str(e)}")
        return False

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

# Authentication Endpoints
@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data = request.json
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        
        # Basic validation
        if not all([name, email, password]):
            return jsonify({"message": "All fields are required"}), 400
            
        # Check if user exists
        existing_user = db.users.find_one({"email": email})
        if existing_user:
            return jsonify({"message": "Email already registered"}), 400
            
        # Hash password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Generate OTP
        otp = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
        otp_expiry = datetime.datetime.now() + datetime.timedelta(minutes=15)
        
        # Store user with OTP
        user = {
            'name': name,
            'email': email,
            'password': hashed_password,
            'otp': otp,
            'otpExpiry': otp_expiry,
            'verified': False,
            'createdAt': datetime.datetime.now(),
            'usageCount': 0,
            'plan': 'free'
        }
        
        db.users.insert_one(user)
        
        # Add this line here to send the email
        send_otp_email(email, otp, name)
        
        print(f"User registered: {email} with OTP: {otp}")
        
        # Return success with OTP (for testing)
        return jsonify({
            "message": "Registration successful! Please check your email for verification code.",
            "otp": otp  # Remove in production
        })
    except Exception as e:
        print(f"Registration error: {str(e)}")
        return jsonify({"message": "Registration failed. Please try again."}), 500

@app.route('/api/auth/verify', methods=['POST'])
def verify():
    try:
        data = request.json
        email = data.get('email')
        otp = data.get('otp')
        
        if not all([email, otp]):
            return jsonify({"message": "Email and OTP are required"}), 400
            
        # Find user
        user = db.users.find_one({"email": email})
        if not user:
            return jsonify({"message": "User not found"}), 400
            
        # Check OTP
        if user.get('otp') != otp:
            return jsonify({"message": "Invalid verification code"}), 400
            
        # Check expiry
        if datetime.datetime.now() > user.get('otpExpiry'):
            return jsonify({"message": "Verification code expired"}), 400
            
        # Update user status and remove OTP fields
        db.users.update_one(
            {"email": email},
            {
                "$set": {"verified": True},
                "$unset": {"otp": "", "otpExpiry": ""}
            }
        )
        
        # Get updated user
        updated_user = db.users.find_one({"email": email})
        
        # Create JWT token
        token = jwt.encode({
            'sub': str(updated_user['_id']),
            'email': updated_user['email'],
            'name': updated_user['name'],
            'exp': datetime.datetime.now() + datetime.timedelta(days=30)
        }, JWT_SECRET)
        
        # Create user object without sensitive data
        user_data = {
            'id': str(updated_user['_id']),
            'name': updated_user['name'],
            'email': updated_user['email'],
            'verified': updated_user['verified'],
            'plan': updated_user.get('plan', 'free'),
            'usageCount': updated_user.get('usageCount', 0)
        }
        
        # Create response with cookie
        response = make_response(jsonify({"message": "Email verified successfully", "user": user_data}))
        response.set_cookie(
            'auth_token', 
            token, 
            httponly=True, 
            secure=True, 
            samesite='None', 
            max_age=30*24*60*60,
            path='/'
        )
        
        return response
    except Exception as e:
        print(f"Verification error: {str(e)}")
        return jsonify({"message": "Verification failed. Please try again."}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        if not all([email, password]):
            return jsonify({"message": "Email and password are required"}), 400
            
        # Find user
        user = db.users.find_one({"email": email})
        if not user:
            return jsonify({"message": "Invalid email or password"}), 401
            
        # Check password
        if not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            return jsonify({"message": "Invalid email or password"}), 401
            
        # Check if verified
        if not user.get('verified', False):
            return jsonify({"message": "Please verify your email before logging in"}), 401
            
        # Create JWT token
        token = jwt.encode({
            'sub': str(user['_id']),
            'email': user['email'],
            'name': user['name'],
            'exp': datetime.datetime.now() + datetime.timedelta(days=30)
        }, JWT_SECRET)
        
        # Create user object without sensitive data
        user_data = {
            'id': str(user['_id']),
            'name': user['name'],
            'email': user['email'],
            'verified': user['verified'],
            'plan': user.get('plan', 'free'),
            'usageCount': user.get('usageCount', 0)
        }
        
        # Create response with cookie
        response = make_response(jsonify({"message": "Login successful", "user": user_data}))
        response.set_cookie(
            'auth_token', 
            token, 
            httponly=True, 
            secure=True, 
            samesite='None', 
            max_age=30*24*60*60,
            path='/'
        )
        
        return response
    except Exception as e:
        print(f"Login error: {str(e)}")
        return jsonify({"message": "Login failed. Please try again."}), 500

@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    try:
        token = request.cookies.get('auth_token')
        
        if not token:
            return jsonify({"user": None})
            
        try:
            # Verify token
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            
            # Get user from database
            user = db.users.find_one({"email": payload['email']})
            
            if not user:
                return jsonify({"user": None})
                
            # Return user data without sensitive fields
            user_data = {
                'id': str(user['_id']),
                'name': user['name'],
                'email': user['email'],
                'verified': user['verified'],
                'plan': user.get('plan', 'free'),
                'usageCount': user.get('usageCount', 0)
            }
            
            return jsonify({"user": user_data})
        except jwt.ExpiredSignatureError:
            return jsonify({"user": None})
        except jwt.InvalidTokenError:
            return jsonify({"user": None})
    except Exception as e:
        print(f"Auth check error: {str(e)}")
        return jsonify({"user": None})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    response = make_response(jsonify({"message": "Logged out successfully"}))
    response.delete_cookie('auth_token', path='/')
    return response

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"})

@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"message": "API is working properly!"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)