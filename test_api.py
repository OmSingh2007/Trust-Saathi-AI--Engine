import requests
import json

# The URL where your local AI Engine (FastAPI) is running
AI_ENGINE_URL = "http://127.0.0.1:8000/extract"

# Make sure you have an image with this exact name in the same folder!
TEST_IMAGE_PATH = "dummy_receipt.jpg" 

def test_ai_extraction():
    print(f"🚀 Sending {TEST_IMAGE_PATH} to your local AI Engine...")
    
    try:
        # Open the image file in binary mode
        with open(TEST_IMAGE_PATH, "rb") as image_file:
            # Prepare the file payload
            files = {"file": (TEST_IMAGE_PATH, image_file, "image/jpeg")}
            
            # Send the POST request to your FastAPI server
            response = requests.post(AI_ENGINE_URL, files=files)
            
            # Print the HTTP status code
            print(f"📡 AI Engine Status Code: {response.status_code}")
            
            if response.status_code in [200, 201, 202]:
                print("✅ Success! Response from your AI Engine:")
                try:
                    print(json.dumps(response.json(), indent=2))
                except json.JSONDecodeError:
                    print(response.text)
            else:
                print("❌ Error processing file:")
                print(response.text)
                
    except FileNotFoundError:
        print(f"❌ Error: Could not find '{TEST_IMAGE_PATH}'.")
        print("💡 Quick Fix: Find any image on your laptop, paste it in this folder, and rename it to 'dummy_receipt.jpg'.")
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: Could not connect to the AI Engine.")
        print("💡 Quick Fix: Make sure your FastAPI server is running in another terminal using 'uvicorn main:app --reload'")
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    test_ai_extraction()