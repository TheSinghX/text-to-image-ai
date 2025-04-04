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

# Logging setup
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Flask app setup
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default_secret_key")

# Database config
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
db.init_app(app)

# Flask-Login setup
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# Guest user limit
app.config['GUEST_LIMIT'] = 1  # Allow 1 image generation for guest users

# Email setup (optional, if you use email features)
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "dreampixel2611@gmail.com"
SMTP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')

# Models
from models import User, Image

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables
with app.app_context():
    db.create_all()

# --- IMAGE GENERATION ROUTE USING STABILITY API ---
@app.route('/generate', methods=['POST'])
def generate_image():
    try:
        data = request.json
        prompt = data.get('prompt', '')

        if not prompt:
            return jsonify({'error': 'Prompt is required'}), 400

        # Check guest generation limit
        if not current_user.is_authenticated:
            if session.get('guest_generations', 0) >= app.config['GUEST_LIMIT']:
                return jsonify({
                    'error': 'Guest Limit Reached',
                    'details': 'You have reached the limit for free image generations. Please sign up or log in.',
                    'require_auth': True
                }), 403

            session['guest_generations'] = session.get('guest_generations', 0) + 1

        STABILITY_API_KEY = os.environ.get("STABILITY_API_KEY")
        if not STABILITY_API_KEY:
            return jsonify({'error': 'API key missing'}), 401

        stability_url = "https://api.stability.ai/v1/generation/stable-diffusion-v1-5/text-to-image"

        headers = {
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "text_prompts": [{"text": prompt}],
            "cfg_scale": 7,
            "clip_guidance_preset": "FAST_BLUE",
            "height": 512,
            "width": 512,
            "samples": 1,
            "steps": 30
        }

        response = requests.post(stability_url, headers=headers, json=payload)
        if response.status_code != 200:
            logger.error(f"Stability API error: {response.status_code}, {response.text}")
            return jsonify({'error': 'Failed to generate image', 'details': response.text}), 500

        image_base64 = response.json()["artifacts"][0]["base64"]

        # Save image to DB
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

    except Exception as e:
        logger.error(f"Error generating image: {e}")
        return jsonify({'error': 'Unexpected error', 'details': str(e)}), 500
