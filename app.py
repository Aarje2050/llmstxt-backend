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

# MongoDB connection - replace the current code with this
try:
    MONGODB_URI = os.environ.get("MONGODB_URI")
    JWT_SECRET = os.environ.get("JWT_SECRET", "default_secret")
    

    print(f"Connecting to MongoDB with URI: {MONGODB_URI[:20]}..." if MONGODB_URI else "MongoDB URI not found")
    print("MONGODB_URI:", repr(MONGODB_URI))
    print("ENV VARS:")
    print(os.environ)


    if not MONGODB_URI or "localhost" in MONGODB_URI:
        raise ValueError("Invalid MongoDB URI. Please set a valid MONGODB_URI environment variable.")
    
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=30000)
    # Force a connection to verify it works
    client.admin.command('ping')
    print("MongoDB connection successful!")
    db = client.llms_txt_generator
    
    # Check if we can access collections
    db.users.find_one({})  # Just to test connection with a simple query
    print("Successfully accessed users collection")
    
except Exception as e:
    print(f"MongoDB connection error: {str(e)}")
    print("Falling back to in-memory storage")
    
    # Create in-memory storage as fallback
    class MemoryDB:
        def __init__(self):
            self.users = MemoryCollection("users")
            self.usage_logs = MemoryCollection("usage_logs")
    
    class MemoryCollection:
        def __init__(self, name):
            self.name = name
            self.data = []
            self.id_counter = 1
        
        def insert_one(self, doc):
            # Add _id if not present
            if '_id' not in doc:
                doc['_id'] = self.id_counter
                self.id_counter += 1
            self.data.append(doc)
            return {'inserted_id': doc['_id']}
        
        def find_one(self, query=None):
            if not query:
                return self.data[0] if self.data else None
                
            for doc in self.data:
                match = True
                for k, v in query.items():
                    if k not in doc or doc[k] != v:
                        match = False
                        break
                if match:
                    return doc
            return None
        
        def update_one(self, query, update, upsert=False):
            # Find matching document
            doc = self.find_one(query)
            
            # If no match and upsert is True, insert a new document
            if not doc and upsert:
                new_doc = {}
                for k, v in query.items():
                    new_doc[k] = v
                
                # Process update operators
                if '$set' in update:
                    for k, v in update['$set'].items():
                        new_doc[k] = v
                
                self.insert_one(new_doc)
                return
            
            # If document found, update it
            if doc:
                # Handle $set operator
                if '$set' in update:
                    for k, v in update['$set'].items():
                        doc[k] = v
                
                # Handle $unset operator
                if '$unset' in update:
                    for k in update['$unset']:
                        if k in doc:
                            del doc[k]
                
                # Handle $inc operator
                if '$inc' in update:
                    for k, v in update['$inc'].items():
                        if k in doc:
                            doc[k] += v
                        else:
                            doc[k] = v
    
    # Create in-memory database as fallback
    db = MemoryDB()
    print("Using in-memory database for testing")

# Function to send OTP email
def send_otp_email(to_email, otp, name):
    try:
        # Get email settings from environment variables
        email_host = os.environ.get('EMAIL_HOST', 'smtp-relay.brevo.com')
        email_port = int(os.environ.get('EMAIL_PORT', 587))
        email_secure = os.environ.get('EMAIL_SECURE', 'false').lower() == 'true'
        email_user = os.environ.get('EMAIL_USER')
        email_password = os.environ.get('EMAIL_PASSWORD')
        email_from = os.environ.get('EMAIL_FROM', '"Immortal" <aarje2050@gmail.com>')
        
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

@app.route('/api/usage/track', methods=['POST'])
def track_usage():
    try:
        # Get the auth token
        token = request.cookies.get('auth_token')
        if not token:
            return jsonify({"message": "Authentication required"}), 401
        
        # Verify token
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            email = payload.get('email')
            
            # Get user from database
            user = db.users.find_one({"email": email})
            if not user:
                return jsonify({"message": "User not found"}), 404
            
            # Get request data
            data = request.json
            urls = data.get('urls', [])
            
            # Update usage count
            db.users.update_one(
                {"email": email},
                {"$inc": {"usageCount": 1}}
            )
            
            # Optionally log detailed usage
            usage_log = {
                "userId": user['_id'],
                "urls": urls,
                "timestamp": datetime.datetime.now()
            }
            db.usage_logs.insert_one(usage_log)
            
            return jsonify({"message": "Usage tracked successfully"})
        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Invalid token"}), 401
    except Exception as e:
        print(f"Error tracking usage: {str(e)}")
        return jsonify({"message": "Failed to track usage"}), 500

@app.route('/api/debug', methods=['GET'])
def debug_info():
    # Don't expose sensitive information in production
    if os.environ.get('ENVIRONMENT') == 'production':
        return jsonify({"message": "Debug endpoint disabled in production"}), 403
        
    # Show environment variables (except secrets)
    env_vars = {}
    for key in os.environ:
        if key not in ['JWT_SECRET', 'MONGODB_URI', 'EMAIL_PASSWORD']:
            env_vars[key] = os.environ[key]
        else:
            env_vars[key] = "[REDACTED]"
    
    # Basic connectivity tests
    mongodb_status = "Working" if isinstance(db, MongoClient) else "Using in-memory fallback"
    
    return jsonify({
        "environment": env_vars,
        "mongodb_status": mongodb_status,
        "time": str(datetime.datetime.now())
    })
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"})

@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"message": "API is working properly!"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)