import sys
import os
from io import BytesIO
from vantbot import image_ops

# Chat with Llava
def chat_with_llava(llava_client, model, prompt, image_url, slack_token):
    try:
        # Use the slack_token for authentication headers if needed
        headers = {'Authorization': f'Bearer {slack_token}'}
        
        # Validate the image URL before sending it to Llava
        validated_url = image_ops.validate_image_url(image_url, headers)
        if "Error" in validated_url:
            return validated_url  # Return the error if the URL is invalid
        
        # Fetch the image data from the validated URL
        image = image_ops.fetch_image_data(validated_url, headers)
        if isinstance(image, str) and "An error occurred" in image:
            return image  # Return the error if fetching the image fails

        # Convert image to bytes for the Llava API
        with BytesIO() as output:
            image.save(output, format="PNG")  # Save image in PNG format
            image_data = output.getvalue()  # Get the byte data

        # Call the Llava API with the prompt and image data
        response = llava_client.chat(
            model=model,
            messages=[
                {"role": "user",
                 "content": prompt,
                 "images": [image_data]  # Include image bytes here
                }
            ]
        )

        return response["message"]["content"]

    except Exception as e:
        return f"An error occurred: {e}"