import sys
import os

# Add backend/ to sys.path so tests can import services, models, etc.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
