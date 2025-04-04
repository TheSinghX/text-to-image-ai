# AICRAFT/__init__.py

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')  # move config to a config.py

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)

    from .models import User, Image
    db.create_all(app=app)

    from .routes import main
    app.register_blueprint(main)

    return app
