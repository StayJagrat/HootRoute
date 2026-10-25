"""The product name in one place. Set APP_NAME in the repo .env to rename everything the agents say."""
from .config import env

BRAND = env("APP_NAME", "HootRoute")
