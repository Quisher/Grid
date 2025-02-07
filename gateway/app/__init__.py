from flask import Flask
from flask_cors import CORS
import os


def create_app(debug=False, n_replica=None):
    """Create flask application."""
    app = Flask(__name__)
    app.debug = debug
    app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
    app.config["N_REPLICA"] = n_replica

    from .main import main as main_blueprint

    app.register_blueprint(main_blueprint)
    CORS(app)
    return app
