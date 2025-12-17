import os

class Config:
    SECRET_KEY = 'Nitesh@@@##$$'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(os.path.dirname(__file__), 'instance', 'attempts.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ONTOLOGY_PATH = os.path.join(os.path.dirname(__file__), 'ontology', 'Math-additions.owl')