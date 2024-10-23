import os
import logging
import sys
from vantbot import variables
import requests

# Function to get Giphy
def get_giphy(query):
    giphy_api_key = os.getenv("GIPHY_API_KEY")
    giphy_url = f"http://api.giphy.com/v1/gifs/search?q={query}&api_key={giphy_api_key}&limit=1"
    variables.app.logger.info(f"Giphy query: {query}")
    try:
        response = requests.get(giphy_url)
        data = response.json()
        if data["data"]:
            # Return the URL of the first GIF
            gif_url = data["data"][0]["images"]["downsized"]["url"]
            variables.app.logger.info(f"Giphy URL: {gif_url}")
            return gif_url
        else:
            return "No GIFs found for this query."
    except Exception as e:
        return f"Error fetching GIF: {e}"