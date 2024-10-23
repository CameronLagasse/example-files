import requests
from PIL import Image
import io
from io import BytesIO

def fetch_image_data(url, headers):
    """Fetch image from the provided URL."""
    try:
        # Use the provided headers to fetch the image
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses

        # Open the image using PIL
        image = Image.open(BytesIO(response.content)).convert('RGB')
        return image  # Return the image object
    except Exception as e:
        return f"An error occurred while fetching the image: {e}"

def validate_image_url(url, headers=None):
    try:
        # Fetch the image from the URL with optional headers
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses

        # Check if the response content type is an image
        content_type = response.headers.get('Content-Type')
        if 'image' not in content_type:
            return f"Error: URL did not return an image. Content-Type: {content_type}"

        # Return the valid image URL
        return url

    except Exception as e:
        return f"An error occurred while validating the image URL: {e}"