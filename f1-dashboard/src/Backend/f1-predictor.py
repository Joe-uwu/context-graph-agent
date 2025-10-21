from flask import Flask, jsonify, request
from f1predictor_functions import F1Predictor
import pandas as pd

app = Flask(__name__)
predictor = F1Predictor()

@app.route('/api/current_season', methods=['GET'])
def get_current_season():
    data = predictor.get_current_season()
    return jsonify(data)

@app.route('/api/driver_standings', methods=['GET'])
def get_driver_standings():
    data = predictor.get_driver_standings()
    return jsonify(data)

@app.route('/api/constructor_standings', methods=['GET'])
def get_constructor_standings():
    data = predictor.get_constructor_standings()
    return jsonify(data)

@app.route('/api/upcoming_races', methods=['GET'])
def get_upcoming_races():
    data = predictor.get_upcoming_races()
    return jsonify(data)

