import os
from dotenv import dotenv_values

UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(UTILS_DIR)
env_config = dotenv_values(os.path.join(PROJECT_DIR, ".env"))
