#!/bin/sh
# Démarre le visualiseur en arrière-plan (port 8053)
python visualization/visualizer.py &

# Démarre l'app principale en premier plan — reçoit les signaux Docker (SIGTERM)
exec python app.py
