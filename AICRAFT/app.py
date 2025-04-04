import os
import base64
import logging
import requests
import json
import time
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import re

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask app
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default_secret_key")

# Configure database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Email configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "dreampixel2611@gmail.com"
SMTP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# Clipdrop API configuration
CLIPDROP_API_KEY = os.environ.get("CLIPDROP_API_KEY")
CLIPDROP_API_URL = "https://clipdrop-api.co/text-to-image/v1"

# User session tracking - limit non-logged in users to 1 generation
app.config['GUEST_LIMIT'] = 1  # Allow 1 image for non-logged-in users

# Import models
from models import User, Image

# Setup user loader callback for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables
with app.app_context():
    db.create_all()

@app.route('/generate', methods=['POST'])
def generate_image():
    """
    Generate an image using Clipdrop API based on the text prompt.
    """
    try:
        data = request.json
        prompt = data.get('prompt', '')
        
        if not prompt:
            return jsonify({'error': 'Prompt is required'}), 400
        
        # Check if guest user has exceeded limit
        if not current_user.is_authenticated:
            if session.get('guest_generations', 0) >= app.config['GUEST_LIMIT']:
                return jsonify({
                    'error': 'Guest Limit Reached',
                    'details': 'You have reached the limit for free image generations. Please sign up or log in to continue.',
                    'require_auth': True
                }), 403
            
            # Increment the guest generation count
            session['guest_generations'] = session.get('guest_generations', 0) + 1
        
        if not CLIPDROP_API_KEY:
            logger.error("No API key found for Clipdrop")
            return jsonify({
                'error': 'API Key Missing', 
                'details': 'Please provide a valid Clipdrop API key to use this service.'
            }), 401
        
        logger.debug(f"Sending request to Clipdrop API with prompt: {prompt}")
        
        headers = {
            "x-api-key": CLIPDROP_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "prompt": prompt,
            "negative_prompt": "blurry, bad quality, distorted, disfigured",
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
            "num_inference_steps": 30
        }
        
        response = requests.post(CLIPDROP_API_URL, headers=headers, json=payload, timeout=120)
        
        if response.status_code != 200:
            logger.error(f"Clipdrop API error: {response.status_code}, {response.text}")
            error_detail = response.json().get('message', f"API returned status code {response.status_code}")
            return jsonify({
                'error': 'Failed to generate image', 
                'details': error_detail
            }), 500
        
        response_data = response.json()
        
        if not response_data.get('image'):  # Adjust this based on Clipdrop API response format
            return jsonify({'error': 'No image was generated'}), 500
        
        image_base64 = response_data['image']
        
        if current_user.is_authenticated:
            new_image = Image(prompt=prompt, image_data=image_base64, user_id=current_user.id)
        else:
            new_image = Image(prompt=prompt, image_data=image_base64)
            
        db.session.add(new_image)
        db.session.commit()
        
        return jsonify({
            'image': image_base64,
            'is_authenticated': current_user.is_authenticated,
            'guest_generations': session.get('guest_generations', 0) if not current_user.is_authenticated else None,
            'guest_limit': app.config['GUEST_LIMIT']
        })
    
    except requests.exceptions.ConnectionError:
        logger.error("Connection error: Could not connect to Clipdrop API")
        return jsonify({
            'error': 'Connection Error', 
            'details': 'Could not connect to Clipdrop API. Please check your internet connection.'
        }), 503
    
    except requests.exceptions.Timeout:
        logger.error("Request timeout: Clipdrop API took too long to respond")
        return jsonify({
            'error': 'Request Timeout', 
            'details': 'Clipdrop API took too long to respond. Try a simpler prompt.'
        }), 504
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            'error': 'Unexpected Error', 
            'details': str(e)
        }), 500
